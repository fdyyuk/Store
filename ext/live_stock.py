"""
Live Stock Manager
Author: fdyyuk
Created at: 2025-03-07 18:30:16 UTC
Last Modified: 2025-03-08 16:06:22 UTC

Dependencies:
- ext.product_manager: For product operations
- ext.balance_manager: For balance operations
- ext.trx: For transaction operations
- ext.admin_service: For maintenance mode
- ext.constants: For configuration and responses
"""

import discord
from discord.ext import commands, tasks
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict

from .constants import (
    COLORS,
    MESSAGES,
    UPDATE_INTERVAL,
    CACHE_TIMEOUT,
    Stock,
    Status,
    CURRENCY_RATES,
    COG_LOADED
)
from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .product_manager import ProductManagerService
from .balance_manager import BalanceManagerService 
from .trx import TransactionManager
from .admin_service import AdminService

class LiveStockManager(BaseLockHandler):
    _instance = None
    _instance_lock = asyncio.Lock()

    def __new__(cls, bot):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, bot):
        if not self.initialized:
            super().__init__()
            self.bot = bot
            self.logger = logging.getLogger("LiveStockManager")
            self.cache_manager = CacheManager()
            
            # Initialize services
            self.product_service = ProductManagerService(bot)
            self.balance_service = BalanceManagerService(bot)
            self.trx_manager = TransactionManager(bot)
            self.admin_service = AdminService(bot)
            
            # Channel configuration
            self.stock_channel_id = int(self.bot.config.get('id_live_stock', 0))
            self.current_stock_message: Optional[discord.Message] = None
            self.button_manager = None
            self.initialized = True

    async def set_button_manager(self, button_manager):
        """Set button manager untuk integrasi"""
        self.button_manager = button_manager

    async def create_stock_embed(self) -> discord.Embed:
        """Buat embed untuk display stock dengan data dari ProductManager"""
        try:
            # Check maintenance mode
            if await self.admin_service.is_maintenance_mode():
                return discord.Embed(
                    title="🔧 Maintenance Mode",
                    description=MESSAGES.INFO['MAINTENANCE'],
                    color=COLORS.WARNING,
                    timestamp=datetime.utcnow()
                )

            # Get products dari ProductManager dengan proper response handling
            cache_key = 'all_products_display'
            cached_products = await self.cache_manager.get(cache_key)
            
            if not cached_products:
                product_response = await self.product_service.get_all_products()
                if not product_response.success:
                    raise ValueError(product_response.error)
                products = product_response.data
                await self.cache_manager.set(
                    cache_key,
                    products,
                    expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.SHORT)
                )
            else:
                products = cached_products
            
            embed = discord.Embed(
                title="🏪 Live Stock Status",
                description=(
                    "```yml\n"
                    "Selamat datang di Growtopia Shop!\n"
                    "Stock dan harga diperbarui secara real-time\n"
                    "```"
                ),
                color=COLORS.INFO
            )

            # Format waktu server
            current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            embed.add_field(
                name="🕒 Server Time",
                value=f"```{current_time} UTC```",
                inline=False
            )

            # Display products dengan format yang lebih rapi
            for product in products:
                try:
                    # Get stock count dengan caching
                    stock_cache_key = f'stock_count_{product["code"]}'
                    stock_count = await self.cache_manager.get(stock_cache_key)
                    
                    if stock_count is None:
                        stock_response = await self.product_service.get_stock_count(product['code'])
                        if not stock_response.success:
                            continue
                        stock_count = stock_response.data
                        await self.cache_manager.set(
                            stock_cache_key,
                            stock_count,
                            expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.SHORT)
                        )
                    
                    # Status emoji based on stock level
                    status_emoji = "🟢" if stock_count > Stock.ALERT_THRESHOLD else "🟡" if stock_count > 0 else "🔴"
                    
                    # Format price using currency rates from constants
                    price = float(product['price'])
                    price_display = self._format_price(price)

                    field_value = (
                        "```yml\n"
                        f"Price : {price_display}\n"
                        f"Stock : {stock_count} unit\n"
                        "```"
                    )
                    
                    # Add description if exists
                    if product.get('description'):
                        field_value = field_value[:-3] + f"Info  : {product['description']}\n```"
                    
                    embed.add_field(
                        name=f"{status_emoji} {product['name']}",
                        value=field_value,
                        inline=True
                    )

                except Exception as e:
                    self.logger.error(f"Error processing product {product.get('name', 'Unknown')}: {e}")
                    continue

            embed.set_footer(text=f"Auto-update setiap {int(UPDATE_INTERVAL.LIVE_STOCK)} detik")
            embed.timestamp = datetime.utcnow()
            return embed

        except Exception as e:
            self.logger.error(f"Error creating stock embed: {e}")
            return discord.Embed(
                title="❌ System Error",
                description=MESSAGES.ERROR['DISPLAY_ERROR'],
                color=COLORS.ERROR
            )

    def _format_price(self, price: float) -> str:
        """Format price dengan currency rates dari constants"""
        try:
            if price >= CURRENCY_RATES['BGL']:
                return f"{price/CURRENCY_RATES['BGL']:.1f} BGL"
            elif price >= CURRENCY_RATES['DL']:
                return f"{price/CURRENCY_RATES['DL']:.0f} DL"
            return f"{int(price)} WL"
        except Exception:
            return "Invalid Price"

    async def update_stock_display(self) -> bool:
        """Update tampilan stock dengan proper error handling"""
        try:
            if not self.current_stock_message or not self.button_manager:
                channel = self.bot.get_channel(self.stock_channel_id)
                if channel:
                    embed = await self.create_stock_embed()
                    self.current_stock_message = await channel.send(embed=embed)
                    return True
                return False

            embed = await self.create_stock_embed()
            await self.current_stock_message.edit(embed=embed)
            return True

        except discord.NotFound:
            self.logger.warning(MESSAGES.WARNING['MESSAGE_NOT_FOUND'])
            self.current_stock_message = None
            return False
            
        except discord.HTTPException as e:
            self.logger.error(f"HTTP error updating stock display: {e}")
            return False
            
        except Exception as e:
            self.logger.error(f"Error updating stock display: {e}")
            try:
                error_embed = discord.Embed(
                    title="❌ System Error",
                    description=MESSAGES.ERROR['DISPLAY_ERROR'],
                    color=COLORS.ERROR
                )
                await self.current_stock_message.edit(embed=error_embed)
            except:
                pass
            return False

    async def cleanup(self):
        """Cleanup resources dengan proper error handling"""
        try:
            if self.current_stock_message:
                embed = discord.Embed(
                    title="🔧 Maintenance",
                    description=MESSAGES.INFO['MAINTENANCE'],
                    color=COLORS.WARNING
                )
                await self.current_stock_message.edit(embed=embed)
                
            # Clear caches
            patterns = [
                'all_products_display',
                'stock_count_*'
            ]
            for pattern in patterns:
                await self.cache_manager.delete_pattern(pattern)
                
            self.logger.info("LiveStockManager cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error in cleanup: {e}")


@commands.Cog
class LiveStockCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.stock_manager = LiveStockManager(bot)
        self.logger = logging.getLogger("LiveStockCog")
        self.update_stock.start()

    def cog_unload(self):
        self.update_stock.cancel()
        asyncio.create_task(self.stock_manager.cleanup())

    @tasks.loop(seconds=UPDATE_INTERVAL.LIVE_STOCK)
    async def update_stock(self):
        """Update stock display periodically"""
        try:
            await self.stock_manager.update_stock_display()
        except Exception as e:
            self.logger.error(f"Error in stock update loop: {e}")

    @update_stock.before_loop
    async def before_update_stock(self):
        """Wait until bot is ready"""
        await self.bot.wait_until_ready()

async def setup(bot):
    """Setup cog dengan proper error handling"""
    if not hasattr(bot, COG_LOADED['LIVE_STOCK']):
        try:
            await bot.add_cog(LiveStockCog(bot))
            setattr(bot, COG_LOADED['LIVE_STOCK'], True)
            logging.info(
                f'LiveStock cog loaded successfully at '
                f'{datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC'
            )
        except Exception as e:
            logging.error(f"Failed to load LiveStock cog: {e}")
            raise