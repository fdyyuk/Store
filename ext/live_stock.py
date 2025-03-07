import logging
import asyncio
from typing import Optional, Dict
from datetime import datetime

import discord
from discord.ext import commands, tasks
from .constants import (
    COLORS,
    UPDATE_INTERVAL,
    CACHE_TIMEOUT  
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
            self.button_manager = None
            self.initialized = True

    async def set_button_manager(self, button_manager):
        """Set button manager untuk sinkronisasi"""
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
                    "Stock diperbarui setiap menit\n"
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
                stock_count = await self.product_manager.get_stock_count(product['name'])
                
                # Emoji status
                status_emoji = "🟢" if stock_count > 0 else "🔴"
                
                # Format harga dalam WL/DL/BGL
                price = product['price']
                if price >= 10000:  # Jika 10k+ WL, tampilkan dalam BGL
                    price_display = f"{price/10000:.1f} BGL"
                elif price >= 100:  # Jika 100+ WL, tampilkan dalam DL
                    price_display = f"{price/100:.0f} DL"
                else:
                    price_display = f"{price} WL"

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

            embed.set_footer(text="Auto-update setiap 55 detik")
            embed.timestamp = datetime.utcnow()
            return embed

        except Exception as e:
            self.logger.error(f"Error creating stock embed: {e}")
            raise

    async def get_or_create_stock_message(self) -> Optional[discord.Message]:
        """Get existing message atau create new one"""
        if not self.stock_channel_id:
            self.logger.error("Stock channel ID not configured!")
            return None
            
        channel = self.bot.get_channel(self.stock_channel_id)
        if not channel:
            self.logger.error(f"Could not find stock channel {self.stock_channel_id}")
            return None
            
        try:
            message_id = await self.cache_manager.get("live_stock_message_id")
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    self.current_stock_message = message
                    return message
                except discord.NotFound:
                    await self.cache_manager.delete("live_stock_message_id")
                except Exception as e:
                    self.logger.error(f"Error fetching stock message: {e}")

            # Buat pesan baru dengan embed
            embed = await self.create_stock_embed()
            message = await channel.send(embed=embed)
            
            self.current_stock_message = message
            await self.cache_manager.set(
                "live_stock_message_id",
                message.id,
                expires_in=CACHE_TIMEOUT,
                permanent=True
            )
            return message

        except Exception as e:
            self.logger.error(f"Error in get_or_create_stock_message: {e}")
            return None

    async def update_stock_display(self) -> bool:
        """Update tampilan stock"""
        try:
            if not self.current_stock_message:
                self.current_stock_message = await self.get_or_create_stock_message()
                
            if not self.current_stock_message:
                return False

            embed = await self.create_stock_embed()
            await self.current_stock_message.edit(embed=embed)
            return True

        except Exception as e:
            self.logger.error(f"Error updating stock display: {e}")
            self.current_stock_message = None  # Reset untuk recreate
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

    @tasks.loop(seconds=UPDATE_INTERVAL)
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
        current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.logger.info(f"Stock display started at: {current_time} UTC")

    async def cog_unload(self):
        self.update_stock.cancel()
        await self.stock_manager.cleanup()
        self.logger.info("LiveStockCog unloaded")

async def setup(bot):
    if not hasattr(bot, 'live_stock_loaded'):
        await bot.add_cog(LiveStockCog(bot))
        bot.live_stock_loaded = True