"""
Live Stock Manager
Author: fdyyuk
Created at: 2025-03-07 18:30:16 UTC
"""

import logging
import asyncio
from typing import Optional, Dict
from datetime import datetime

import discord
from discord.ext import commands, tasks
from .constants import (
    COLORS,
    UPDATE_INTERVAL,
    CACHE_TIMEOUT,
    Stock,
    CURRENCY_RATES
)

from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .product_manager import ProductManagerService

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
            self.product_manager = ProductManagerService(bot)
            self.stock_channel_id = int(self.bot.config.get('id_live_stock', 0))
            self.current_stock_message: Optional[discord.Message] = None
            self.button_manager = None  # Akan diset dari LiveButtonManager
            self.initialized = True

    async def set_button_manager(self, button_manager):
        """Set button manager untuk integrasi"""
        self.button_manager = button_manager

    async def create_stock_embed(self) -> discord.Embed:
        """Buat embed untuk display stock"""
        try:
            products = await self.product_manager.get_all_products()
            
            embed = discord.Embed(
                title="🏪 Live Stock Status",
                description=(
                    "```yml\n"
                    "Selamat datang di Growtopia Shop!\n"
                    "Stock dan harga diperbarui secara real-time\n"
                    "```"
                ),
                color=COLORS['info']
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
                    stock_count = await self.product_manager.get_stock_count(product['name'])
                    
                    # Emoji status berdasarkan threshold
                    status_emoji = "🟢" if stock_count > Stock.ALERT_THRESHOLD else "🟡" if stock_count > 0 else "🔴"
                    
                    # Format harga dalam WL/DL/BGL
                    try:
                        price = float(product['price'])
                        if price >= CURRENCY_RATES.RATES['BGL']:
                            price_display = f"{price/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
                        elif price >= CURRENCY_RATES.RATES['DL']:
                            price_display = f"{price/CURRENCY_RATES.RATES['DL']:.0f} DL"
                        else:
                            price_display = f"{int(price)} WL"
                    except (ValueError, TypeError):
                        price_display = "Invalid Price"
                        self.logger.error(f"Invalid price format for product {product['name']}: {product['price']}")

                    field_value = (
                        "```yml\n"
                        f"Price : {price_display}\n"
                        f"Stock : {stock_count} unit\n"
                        "```"
                    )
                    
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
                description="```diff\n- Live stock display is currently unavailable\n- Please try again later or contact admin\n```",
                color=COLORS['error']
            )

    async def update_stock_display(self) -> bool:
        """Update tampilan stock"""
        try:
            if not self.current_stock_message or not self.button_manager:
                # Biarkan button manager yang membuat pesan
                return False

            embed = await self.create_stock_embed()
            await self.current_stock_message.edit(embed=embed)
            return True

        except Exception as e:
            self.logger.error(f"Error updating stock display: {e}")
            error_embed = discord.Embed(
                title="❌ System Error",
                description="```diff\n- Live stock display is currently unavailable\n- System will attempt to recover automatically\n```",
                color=COLORS['error']
            )
            try:
                await self.current_stock_message.edit(embed=error_embed)
            except:
                pass
            return False

    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.current_stock_message:
                embed = discord.Embed(
                    title="🔧 Maintenance",
                    description="```\nToko sedang dalam maintenance\nMohon tunggu sebentar\n```",
                    color=COLORS['warning']
                )
                await self.current_stock_message.edit(embed=embed)
        except Exception as e:
            self.logger.error(f"Error in cleanup: {e}")

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
        """Wait until bot is ready before starting the loop"""
        await self.bot.wait_until_ready()
        self.logger.info(f"Stock display started at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

async def setup(bot):
    """Setup LiveStockCog"""
    if not hasattr(bot, 'live_stock_loaded'):
        try:
            await bot.add_cog(LiveStockCog(bot))
            bot.live_stock_loaded = True
            logging.info("LiveStockCog loaded successfully")
        except Exception as e:
            logging.error(f"Failed to load LiveStockCog: {e}")
            raise