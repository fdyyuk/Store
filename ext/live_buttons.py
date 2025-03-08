"""
Live Buttons Manager with Shop Integration
Author: fdyyuk
Created at: 2025-03-07 22:35:08 UTC
Last Modified: 2025-03-08 05:59:13 UTC
"""

import logging
import asyncio
from typing import Optional, List, Dict
from datetime import datetime

import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput, Select

from .constants import (
    COLORS,
    MESSAGES,
    BUTTON_IDS,
    CACHE_TIMEOUT,
    Stock,
    Balance,
    TransactionType,
    Status,
    CURRENCY_RATES,
    UPDATE_INTERVAL,
    COOLDOWN_TIME
)

from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .product_manager import ProductManagerService
from .balance_manager import BalanceManagerService
from .models import Transaction, Product

# [rest of the code...]
# Custom Exceptions
class ShopError(Exception):
    """Base exception for shop errors"""
    pass

class InsufficientStockError(ShopError):
    """Raised when product stock is insufficient"""
    pass

class InsufficientBalanceError(ShopError):
    """Raised when user balance is insufficient"""
    pass

class TransactionError(ShopError):
    """Raised when transaction fails"""
    pass

class ProductSelect(Select):
    def __init__(self, products: List[Dict], balance_manager, product_manager):
        self.products_cache = {p['code']: p for p in products}
        self.balance_manager = balance_manager
        self.product_manager = product_manager
        
        options = [
            discord.SelectOption(
                label=f"{product['name']}",
                description=f"Stok: {product['stock']} | Harga: {product['price']} WL",
                value=product['code'],
                emoji="🛍️"
            ) for product in products[:25]  # Discord limit 25 options
        ]
        super().__init__(
            placeholder="Pilih produk yang ingin dibeli...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            selected_code = self.values[0]
            selected_product = self.products_cache.get(selected_code)
            
            if not selected_product:
                raise ValueError(MESSAGES.ERROR['PRODUCT_NOT_FOUND'])
            
            # Verifikasi stock realtime
            current_stock = await self.product_manager.get_stock_count(selected_code)
            if current_stock <= 0:
                raise ValueError(MESSAGES.ERROR['OUT_OF_STOCK'])
            
            # Verifikasi user balance
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])
                
            await interaction.followup.send_modal(
                QuantityModal(selected_code, min(current_stock, 999))
            )
            
        except Exception as e:
            error_msg = str(e) if isinstance(e, ValueError) else MESSAGES.ERROR['TRANSACTION_FAILED']
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description=error_msg,
                    color=COLORS.ERROR
                ),
                ephemeral=True
            )

class RegisterModal(Modal):
    def __init__(self):
        super().__init__(title="📝 Pendaftaran GrowID")
        
        self.growid = TextInput(
            label="Masukkan GrowID Anda",
            placeholder="Contoh: GROW_ID",
            min_length=3,
            max_length=30,
            required=True
        )
        self.add_item(self.growid)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            balance_manager = BalanceManagerService(interaction.client)
            
            growid = str(self.growid.value).strip().upper()
            if not growid or len(growid) < 3:
                raise ValueError(MESSAGES.ERROR['INVALID_GROWID'])
            
            # Cek duplikat GrowID
            existing_user = await balance_manager.get_user_by_growid(growid)
            if existing_user:
                raise ValueError(MESSAGES.ERROR['GROWID_EXISTS'])
                
            await balance_manager.register_user(
                str(interaction.user.id),
                growid
            )
            
            success_embed = discord.Embed(
                title="✅ Berhasil",
                description=MESSAGES.SUCCESS['REGISTRATION'].format(growid=growid),
                color=COLORS.SUCCESS
            )
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            
        except ValueError as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['REGISTRATION_FAILED'],
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

class ShopView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.balance_manager = BalanceManagerService(bot)
        self.product_manager = ProductManagerService(bot)
        self.logger = logging.getLogger("ShopView")
        self._interaction_locks = {}
        self._last_cleanup = datetime.utcnow()

    async def _cleanup_locks(self):
        """Cleanup old locks periodically"""
        now = datetime.utcnow()
        if (now - self._last_cleanup).total_seconds() > 300:  # Every 5 minutes
            self._interaction_locks.clear()
            self._last_cleanup = now

    async def _acquire_interaction_lock(self, interaction_id: str) -> bool:
        await self._cleanup_locks()
        
        if interaction_id not in self._interaction_locks:
            self._interaction_locks[interaction_id] = asyncio.Lock()
        
        try:
            await asyncio.wait_for(
                self._interaction_locks[interaction_id].acquire(),
                timeout=3.0
            )
            return True
        except:
            return False

    def _release_interaction_lock(self, interaction_id: str):
        if interaction_id in self._interaction_locks:
            try:
                if self._interaction_locks[interaction_id].locked():
                    self._interaction_locks[interaction_id].release()
            except:
                pass

    @discord.ui.button(
        style=discord.ButtonStyle.primary,
        label="📝 Daftar",
        custom_id=BUTTON_IDS.REGISTER
    )
    async def register_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Mohon Tunggu",
                    description=MESSAGES.INFO['COOLDOWN'],
                    color=COLORS.WARNING
                ),
                ephemeral=True
            )
            return

        try:
            existing_growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if existing_growid:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Sudah Terdaftar",
                        description=f"Anda sudah terdaftar dengan GrowID: `{existing_growid}`",
                        color=COLORS.ERROR
                    ),
                    ephemeral=True
                )
                return

            modal = RegisterModal()
            await interaction.response.send_modal(modal)

        except Exception as e:
            self.logger.error(f"Error in register callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Error",
                        description=MESSAGES.ERROR['REGISTRATION_FAILED'],
                        color=COLORS.ERROR
                    ),
                    ephemeral=True
                )
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.success,
        label="💰 Saldo",
        custom_id=BUTTON_IDS.BALANCE
    )
    async def balance_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Mohon Tunggu",
                    description=MESSAGES.INFO['COOLDOWN'],
                    color=COLORS.WARNING
                ),
                ephemeral=True
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            balance = await self.balance_manager.get_balance(growid)
            if not balance:
                raise ValueError(MESSAGES.ERROR['BALANCE_NOT_FOUND'])

            # Format balance untuk display
            balance_wls = balance.total_wl()
            if balance_wls >= CURRENCY_RATES.RATES['BGL']:
                display_balance = f"{balance_wls/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
            elif balance_wls >= CURRENCY_RATES.RATES['DL']:
                display_balance = f"{balance_wls/CURRENCY_RATES.RATES['DL']:.0f} DL"
            else:
                display_balance = f"{balance_wls} WL"

            embed = discord.Embed(
                title="💰 Informasi Saldo",
                description=f"Saldo untuk `{growid}`",
                color=COLORS.INFO
            )
            
            embed.add_field(
                name="Saldo Saat Ini",
                value=f"```yml\n{display_balance}```",
                inline=False
            )
            
            # Get transaction history
            transactions = await self.balance_manager.get_transaction_history(growid, limit=3)
            if transactions:
                trx_details = []
                for trx in transactions:
                    old_balance = Balance.from_string(trx['old_balance'])
                    new_balance = Balance.from_string(trx['new_balance'])
                    change = new_balance.total_wl() - old_balance.total_wl()
                    sign = "+" if change >= 0 else ""
                    
                    trx_details.append(
                        f"• {trx['type']}: {sign}{change} WL - {trx['details']}"
                    )
                
                embed.add_field(
                    name="Transaksi Terakhir",
                    value=f"```yml\n{chr(10).join(trx_details)}```",
                    inline=False
                )

            embed.set_footer(text="Diperbarui")
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except ValueError as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error in balance callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['BALANCE_FAILED'],
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        label="🌎 World Info",
        custom_id=BUTTON_IDS.WORLD_INFO
    )
    async def world_info_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Mohon Tunggu",
                    description=MESSAGES.INFO['COOLDOWN'],
                    color=COLORS.WARNING
                ),
                ephemeral=True
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)
            
            # Try to get from cache first
            cache_key = 'world_info'
            world_info = await self.cache_manager.get(cache_key)
            
            if not world_info:
                world_info = await self.product_manager.get_world_info()
                if world_info:
                    await self.cache_manager.set(
                        cache_key,
                        world_info,
                        expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.MEDIUM)
                    )
            
            embed = discord.Embed(
                title="🌎 World Information",
                color=COLORS.INFO
            )
            
            embed.add_field(
                name="Detail World",
                value=(
                    "```yml\n"
                    f"World Name : {world_info['name']}\n"
                    f"Owner      : {world_info['owner']}\n"
                    f"Bot        : {world_info['bot']}\n"
                    f"Status     : {world_info['status']}\n"
                    "```"
                ),
                inline=False
            )
            
            if 'description' in world_info:
                embed.add_field(
                    name="Deskripsi",
                    value=f"```{world_info['description']}```",
                    inline=False
                )
            
            embed.set_footer(text="Last Updated")
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in world info callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['WORLD_INFO_FAILED'],
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.success,
        label="🛒 Beli",
        custom_id=BUTTON_IDS.BUY
    )
    async def buy_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Mohon Tunggu", 
                    description=MESSAGES.INFO['COOLDOWN'],
                    color=COLORS.WARNING
                ),
                ephemeral=True
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            # Get products from cache first
            cache_key = 'available_products'
            available_products = await self.cache_manager.get(cache_key)
            
            if not available_products:
                products = await self.product_manager.get_all_products()
                available_products = []
                
                for product in products:
                    stock_count = await self.product_manager.get_stock_count(product['code'])
                    if stock_count > 0:
                        product['stock'] = stock_count
                        available_products.append(product)
                
                if available_products:
                    await self.cache_manager.set(
                        cache_key,
                        available_products,
                        expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.SHORT)
                    )

            if not available_products:
                raise ValueError(MESSAGES.ERROR['OUT_OF_STOCK'])

            embed = discord.Embed(
                title="🏪 Daftar Produk",
                description=(
                    "```yml\n"
                    "Pilih produk dari menu di bawah untuk membeli\n"
                    "```"
                ),
                color=COLORS.INFO
            )

            for product in available_products:
                # Format harga dengan currency rates
                price = float(product['price'])
                if price >= CURRENCY_RATES.RATES['BGL']:
                    price_display = f"{price/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
                elif price >= CURRENCY_RATES.RATES['DL']:
                    price_display = f"{price/CURRENCY_RATES.RATES['DL']:.0f} DL"
                else:
                    price_display = f"{int(price)} WL"
                    
                embed.add_field(
                    name=f"{product['name']} [{product['code']}]",
                    value=(
                        f"```yml\n"
                        f"Harga: {price_display}\n"
                        f"Stok: {product['stock']} unit\n"
                        f"```"
                        f"{product.get('description', '')}"
                    ),
                    inline=True
                )

            view = View(timeout=300)
            view.add_item(ProductSelect(
                available_products,
                self.balance_manager,
                self.product_manager
            ))
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except ValueError as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error in buy callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['TRANSACTION_FAILED'],
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        label="📜 Riwayat",
        custom_id=BUTTON_IDS.HISTORY
    )
    async def history_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏳ Mohon Tunggu",
                    description=MESSAGES.INFO['COOLDOWN'],
                    color=COLORS.WARNING
                ),
                ephemeral=True
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            transactions = await self.balance_manager.get_transaction_history(growid, limit=5)
            if not transactions:
                raise ValueError(MESSAGES.ERROR['NO_HISTORY'])

            embed = discord.Embed(
                title="📊 Riwayat Transaksi",
                description=f"Transaksi terakhir untuk `{growid}`",
                color=COLORS.INFO
            )

            for i, trx in enumerate(transactions, 1):
                # Set emoji berdasarkan tipe transaksi
                emoji_map = {
                    TransactionType.DEPOSIT.value: "💰",
                    TransactionType.PURCHASE.value: "🛒",
                    TransactionType.WITHDRAWAL.value: "💸"
                }
                emoji = emoji_map.get(trx['type'], "❓")
                
                # Format timestamp
                timestamp = datetime.fromisoformat(trx['created_at'].replace('Z', '+00:00'))
                
                # Calculate balance change
                old_balance = Balance.from_string(trx['old_balance'])
                new_balance = Balance.from_string(trx['new_balance'])
                balance_change = new_balance.total_wl() - old_balance.total_wl()
                
                # Format balance change
                if balance_change >= CURRENCY_RATES.RATES['BGL']:
                    change_display = f"{balance_change/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
                elif balance_change >= CURRENCY_RATES.RATES['DL']:
                    change_display = f"{balance_change/CURRENCY_RATES.RATES['DL']:.0f} DL"
                else:
                    change_display = f"{balance_change} WL"
                
                change_prefix = "+" if balance_change >= 0 else ""
                
                embed.add_field(
                    name=f"{emoji} Transaksi #{i}",
                    value=(
                        f"```yml\n"
                        f"Tipe: {trx['type']}\n"
                        f"Tanggal: {timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                        f"Perubahan: {change_prefix}{change_display}\n"
                        f"Status: {trx['status']}\n"
                        f"Detail: {trx['details']}\n"
                        "```"
                    ),
                    inline=False
                )

            embed.set_footer(text="Menampilkan 5 transaksi terakhir")
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except ValueError as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error in history callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['TRANSACTION_FAILED'],
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

# [LiveButtonManager dan LiveButtonsCog tetap sama...]

class LiveButtonManager(BaseLockHandler):
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
            self.logger = logging.getLogger("LiveButtonManager")
            self.cache_manager = CacheManager()
            self.stock_channel_id = int(self.bot.config.get('id_live_stock', 0))
            self.current_message: Optional[discord.Message] = None
            self.stock_manager = None
            self.initialized = True

    async def set_stock_manager(self, stock_manager):
        """Set stock manager untuk integrasi"""
        self.stock_manager = stock_manager
        # Set referensi balik ke stock manager
        await stock_manager.set_button_manager(self)

    async def get_or_create_message(self) -> Optional[discord.Message]:
        """Create or get existing message with both stock display and buttons"""
        if not self.stock_channel_id:
            self.logger.error("Stock channel ID not configured!")
            return None

        channel = self.bot.get_channel(self.stock_channel_id)
        if not channel:
            self.logger.error(f"Channel stock dengan ID {self.stock_channel_id} tidak ditemukan")
            return None

        try:
            message_id = await self.cache_manager.get("live_stock_message_id")
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    self.current_message = message
                    if self.stock_manager:
                        self.stock_manager.current_stock_message = message
                    return message
                except discord.NotFound:
                    await self.cache_manager.delete("live_stock_message_id")
                except Exception as e:
                    self.logger.error(f"Error mengambil pesan: {e}")

            # Buat pesan baru dengan embed dan view
            embed = await self.stock_manager.create_stock_embed() if self.stock_manager else discord.Embed(
                title="🏪 Live Stock",
                description="Loading...",
                color=COLORS.INFO
            )
            view = ShopView(self.bot)
            message = await channel.send(embed=embed, view=view)
            
            self.current_message = message
            if self.stock_manager:
                self.stock_manager.current_stock_message = message
                
            await self.cache_manager.set(
                "live_stock_message_id",
                message.id,
                expires_in=CACHE_TIMEOUT.PERMANENT
            )
            return message

        except Exception as e:
            self.logger.error(f"Error in get_or_create_message: {e}")
            return None

    async def update_buttons(self) -> bool:
        """Update buttons display"""
        try:
            if not self.current_message:
                self.current_message = await self.get_or_create_message()
                
            if not self.current_message:
                return False

            view = ShopView(self.bot)
            await self.current_message.edit(view=view)
            return True

        except Exception as e:
            self.logger.error(f"Error updating buttons: {e}")
            return False

    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.current_message:
                embed = discord.Embed(
                    title="🛠️ Maintenance",
                    description=MESSAGES.INFO['MAINTENANCE'],
                    color=COLORS.WARNING
                )
                await self.current_message.edit(embed=embed, view=None)
        except Exception as e:
            self.logger.error(f"Error in cleanup: {e}")

class LiveButtonsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.button_manager = LiveButtonManager(bot)
        self.stock_manager = None
        self.logger = logging.getLogger("LiveButtonsCog")

    @commands.Cog.listener()
    async def on_ready(self):
        """Setup buttons when bot is ready"""
        await self.button_manager.update_buttons()

    async def cog_load(self):
        """Setup when cog is loaded"""
        self.logger.info("LiveButtonsCog loading...")
        stock_cog = self.bot.get_cog('LiveStockCog')
        if stock_cog:
            self.stock_manager = stock_cog.stock_manager
            await self.button_manager.set_stock_manager(self.stock_manager)

    async def cog_unload(self):
        await self.button_manager.cleanup()
        self.logger.info("LiveButtonsCog unloaded")

async def setup(bot):
    """Setup LiveButtonsCog"""
    if not hasattr(bot, 'live_buttons_loaded'):
        await bot.add_cog(LiveButtonsCog(bot))
        bot.live_buttons_loaded = True
        logging.info("LiveButtonsCog loaded successfully")