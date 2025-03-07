"""
Live Buttons Manager with Shop Integration
Author: fdyyuk
Created at: 2025-03-07 18:33:18 UTC
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
    Balance,
    TransactionType,
    BUTTON_IDS,
    CURRENCY_RATES,
    CACHE_TIMEOUT,
    Stock
)

from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .product_manager import ProductManagerService
from .balance_manager import BalanceManagerService

class PurchaseConfirmModal(Modal):
    def __init__(self, product_code: str, price: int):
        super().__init__(title="🛍️ Konfirmasi Pembelian")
        self.product_code = product_code
        self.price = price
        
        self.quantity = TextInput(
            label="Jumlah yang ingin dibeli",
            placeholder="Masukkan jumlah...",
            min_length=1,
            max_length=3,
            required=True
        )
        self.add_item(self.quantity)

class ShopView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)  # View persisten
        self.bot = bot
        self.balance_manager = BalanceManagerService(bot)
        self.product_manager = ProductManagerService(bot)
        self.logger = logging.getLogger("ShopView")
        self._interaction_locks = {}

    async def _acquire_interaction_lock(self, interaction_id: str) -> bool:
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
                    description=MESSAGES.INFO['COOLDOWN'].format(time=3),
                    color=COLORS['warning']
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
                        color=COLORS['error']
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
                        description=MESSAGES.ERROR['TRANSACTION_FAILED'],
                        color=COLORS['error']
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
                    description=MESSAGES.INFO['COOLDOWN'].format(time=3),
                    color=COLORS['warning']
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

            embed = discord.Embed(
                title="💰 Informasi Saldo",
                description=f"Saldo untuk `{growid}`",
                color=COLORS['info']
            )
            
            # Format balance dengan currency rates
            balance_wls = balance.get_total_wls()
            if balance_wls >= CURRENCY_RATES.RATES['BGL']:
                display_balance = f"{balance_wls/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
            elif balance_wls >= CURRENCY_RATES.RATES['DL']:
                display_balance = f"{balance_wls/CURRENCY_RATES.RATES['DL']:.0f} DL"
            else:
                display_balance = f"{balance_wls} WL"
                
            embed.add_field(
                name="Saldo Saat Ini",
                value=f"```yml\n{display_balance}```",
                inline=False
            )
            
            transactions = await self.balance_manager.get_transaction_history(growid, limit=3)
            if transactions:
                latest_transactions = "\n".join([
                    f"• {trx['type']}: {trx['details']}"
                    for trx in transactions
                ])
                embed.add_field(
                    name="Transaksi Terakhir",
                    value=f"```yml\n{latest_transactions}```",
                    inline=False
                )

            embed.set_footer(text="Diperbarui")
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in balance callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['TRANSACTION_FAILED'],
                color=COLORS['error']
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
                    description=MESSAGES.INFO['COOLDOWN'].format(time=3),
                    color=COLORS['warning']
                ),
                ephemeral=True
            )
            return
            
        try:
            await interaction.response.defer(ephemeral=True)
            
            world_info = await self.product_manager.get_world_info()
            
            embed = discord.Embed(
                title="🌎 World Information",
                color=COLORS['info']
            )
            
            embed.add_field(
                name="Detail World",
                value=(
                    "```yml\n"
                    f"World Name : {world_info['name']}\n"
                    f"Owner      : {world_info['owner']}\n"
                    f"Bot        : {world_info['bot']}\n"
                    "```"
                ),
                inline=False
            )
            
            embed.set_footer(text="Last Updated")
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in world info callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['TRANSACTION_FAILED'],
                color=COLORS['error']
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
                    description=MESSAGES.INFO['COOLDOWN'].format(time=3),
                    color=COLORS['warning']
                ),
                ephemeral=True
            )
            return
            
        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            products = await self.product_manager.get_all_products()
            available_products = []
            
            for product in products:
                stock_count = await self.product_manager.get_stock_count(product['code'])
                if stock_count > 0:
                    product['stock'] = stock_count
                    available_products.append(product)

            if not available_products:
                raise ValueError(MESSAGES.ERROR['OUT_OF_STOCK'])

            embed = discord.Embed(
                title="🏪 Daftar Produk",
                description="Pilih produk dari menu di bawah untuk membeli",
                color=COLORS['info']
            )

            for product in available_products:
                # Format harga
                price = float(product['price'])
                if price >= CURRENCY_RATES.RATES['BGL']:
                    price_display = f"{price/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
                elif price >= CURRENCY_RATES.RATES['DL']:
                    price_display = f"{price/CURRENCY_RATES.RATES['DL']:.0f} DL"
                else:
                    price_display = f"{int(price)} WL"
                    
                embed.add_field(
                    name=f"{product['name']} ({product['code']})",
                    value=(
                        f"```yml\n"
                        f"Harga: {price_display}\n"
                        f"Stok: {product['stock']} unit\n"
                        f"```"
                        f"{product.get('description', 'Tidak ada deskripsi')}"
                    ),
                    inline=True
                )

            view = View(timeout=300)
            view.add_item(ProductSelect(available_products))
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in buy callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['TRANSACTION_FAILED'],
                color=COLORS['error']
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
                    description=MESSAGES.INFO['COOLDOWN'].format(time=3),
                    color=COLORS['warning']
                ),
                ephemeral=True
            )
            return
            
        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            history = await self.balance_manager.get_transaction_history(growid, limit=5)
            if not history:
                raise ValueError(MESSAGES.ERROR['NO_HISTORY'])

            embed = discord.Embed(
                title="📊 Riwayat Transaksi",
                description=f"Transaksi terakhir untuk `{growid}`",
                color=COLORS['info']
            )

            for i, trx in enumerate(history, 1):
                emoji = "💰" if trx['type'] == TransactionType.DEPOSIT.value else "🛒" if trx['type'] == TransactionType.PURCHASE.value else "💸"
                
                timestamp = datetime.fromisoformat(trx['created_at'].replace('Z', '+00:00'))
                
                embed.add_field(
                    name=f"{emoji} Transaksi #{i}",
                    value=(
                        f"```yml\n"
                        f"Tipe: {trx['type']}\n"
                        f"Tanggal: {timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                        f"Detail: {trx['details']}\n"
                        f"Status: {trx['status']}\n"
                        "```"
                    ),
                    inline=False
                )

            embed.set_footer(text="Menampilkan 5 transaksi terakhir")
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in history callback: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description=MESSAGES.ERROR['TRANSACTION_FAILED'],
                color=COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

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
            if not growid:
                raise ValueError(MESSAGES.ERROR['INVALID_GROWID'])
                
            await balance_manager.register_user(
                str(interaction.user.id),
                growid
            )
            
            success_embed = discord.Embed(
                title="✅ Berhasil",
                description=MESSAGES.SUCCESS['REGISTRATION'].format(growid=growid),
                color=COLORS['success']
            )
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"```diff\n- {str(e)}```",
                color=COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

class ProductSelect(discord.ui.Select):
    def __init__(self, products):
        options = []
        for product in products:
            # Format harga untuk display
            price = float(product['price'])
            if price >= CURRENCY_RATES.RATES['BGL']:
                price_display = f"{price/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
            elif price >= CURRENCY_RATES.RATES['DL']:
                price_display = f"{price/CURRENCY_RATES.RATES['DL']:.0f} DL"
            else:
                price_display = f"{int(price)} WL"
                
            option = discord.SelectOption(
                label=f"{product['name']} ({price_display})",
                value=product['code'],
                description=f"Stok: {product['stock']} unit"
            )
            options.append(option)
            
        super().__init__(
            placeholder="Pilih produk yang ingin dibeli...",
            min_values=1,
            max_values=1,
            options=options
        )
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            product_manager = ProductManagerService(interaction.client)
            balance_manager = BalanceManagerService(interaction.client)
            
            product = await product_manager.get_product(self.values[0])
            if not product:
                raise ValueError(MESSAGES.ERROR['PRODUCT_NOT_FOUND'])
                
            stock = await product_manager.get_stock_count(product['code'])
            if stock <= 0:
                raise ValueError(MESSAGES.ERROR['OUT_OF_STOCK'])

            # Format harga
            price = float(product['price'])
            if price >= CURRENCY_RATES.RATES['BGL']:
                price_display = f"{price/CURRENCY_RATES.RATES['BGL']:.1f} BGL"
            elif price >= CURRENCY_RATES.RATES['DL']:
                price_display = f"{price/CURRENCY_RATES.RATES['DL']:.0f} DL"
            else:
                price_display = f"{int(price)} WL"
                
            embed = discord.Embed(
                title="🛍️ Konfirmasi Pembelian",
                description=(
                    f"```yml\n"
                    f"Produk: {product['name']}\n"
                    f"Harga: {price_display}\n"
                    f"Stok: {stock} unit\n"
                    f"```"
                ),
                color=COLORS['info']
            )
            
            # Create confirmation view
            view = View(timeout=180)
            view.add_item(
                Button(
                    style=discord.ButtonStyle.success,
                    label="✅ Konfirmasi",
                    custom_id=f"{BUTTON_IDS.CONFIRM_PURCHASE}_{product['code']}"
                )
            )
            view.add_item(
                Button(
                    style=discord.ButtonStyle.danger,
                    label="❌ Batal",
                    custom_id=BUTTON_IDS.CANCEL_PURCHASE
                )
            )
            
            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )
            
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"```diff\n- {str(e)}```",
                color=COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

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

            # Buat pesan baru dengan embed dari stock manager dan view buttons
            embed = await self.stock_manager.create_stock_embed() if self.stock_manager else discord.Embed(title="Loading...")
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
                    color=COLORS['warning']
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
    if not hasattr(bot, 'live_buttons_loaded'):
        await bot.add_cog(LiveButtonsCog(bot))
        bot.live_buttons_loaded = True
        logging.info("LiveButtonsCog loaded successfully")