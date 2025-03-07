import logging
import asyncio
from typing import Optional, List, Dict
from datetime import datetime

import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput, Select
from .constants import (
    COLORS,        # Untuk warna embed
    MESSAGES,      # Untuk pesan response
    Balance,       # Untuk display balance
    TransactionType # Untuk tipe transaksi
)

from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .product_manager import ProductManagerService
from .balance_manager import BalanceManagerService

class ShopView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)  # View persisten tanpa timeout
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
        custom_id="register"
    )
    async def register_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                "Mohon tunggu, permintaan sebelumnya sedang diproses...",
                ephemeral=True
            )
            return
            
        try:
            existing_growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if existing_growid:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Error",
                        description=f"Anda sudah terdaftar dengan GrowID: {existing_growid}",
                        color=COLORS['error']
                    ),
                    ephemeral=True
                )
                return
    
            modal = RegisterModal()
            await interaction.response.send_modal(modal)
    
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Error",
                        description=f"```diff\n- {str(e)}```",
                        color=COLORS['error']
                    ),
                    ephemeral=True
                )
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.success,
        label="💰 Saldo",
        custom_id="balance"
    )
    async def balance_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                "Mohon tunggu, permintaan sebelumnya sedang diproses...",
                ephemeral=True
            )
            return
            
        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError("Silakan daftar GrowID Anda terlebih dahulu!")

            balance = await self.balance_manager.get_balance(growid)
            if not balance:
                raise ValueError("Tidak dapat mengambil data saldo")

            embed = discord.Embed(
                title="💰 Informasi Saldo",
                description=f"Saldo untuk `{growid}`",
                color=COLORS['info']
            )
            
            embed.add_field(
                name="Saldo Saat Ini",
                value=f"```yml\n{balance.format()}```",
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
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"```diff\n- {str(e)}```",
                color=COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        label="🌎 World Info",
        custom_id="world_info"
    )
    async def world_info_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                "Mohon tunggu, permintaan sebelumnya sedang diproses...",
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
                name="Details",
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
            error_embed = discord.Embed(
                title="❌ Error", 
                description=f"```diff\n- {str(e)}```",
                color=COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        label="🛒 Beli",
        custom_id="buy"
    )
    async def buy_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                "Mohon tunggu, permintaan sebelumnya sedang diproses...",
                ephemeral=True
            )
            return
            
        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError("Silakan daftar GrowID Anda terlebih dahulu!")

            products = await self.product_manager.get_all_products()
            available_products = []
            
            for product in products:
                stock_count = await self.product_manager.get_stock_count(product['code'])
                if stock_count > 0:
                    product['stock'] = stock_count
                    available_products.append(product)

            if not available_products:
                raise ValueError("Tidak ada produk yang tersedia saat ini")

            embed = discord.Embed(
                title="🏪 Daftar Produk",
                description="Pilih produk dari menu di bawah untuk membeli",
                color=COLORS['info']
            )

            for product in available_products:
                embed.add_field(
                    name=f"{product['name']} ({product['code']})",
                    value=(
                        f"```yml\n"
                        f"Harga: {product['price']:,} WL\n"
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
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"```diff\n- {str(e)}```",
                color=COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        label="📜 Riwayat",
        custom_id="history"
    )
    async def history_callback(self, interaction: discord.Interaction, button: Button):
        if not await self._acquire_interaction_lock(str(interaction.id)):
            await interaction.response.send_message(
                "Mohon tunggu, permintaan sebelumnya sedang diproses...",
                ephemeral=True
            )
            return
            
        try:
            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(str(interaction.user.id))
            if not growid:
                raise ValueError("Silakan daftar GrowID Anda terlebih dahulu!")

            history = await self.balance_manager.get_transaction_history(growid, limit=5)
            if not history:
                raise ValueError("Tidak ada riwayat transaksi")

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
                        f"Saldo Awal: {trx['old_balance']}\n"
                        f"Saldo Akhir: {trx['new_balance']}\n"
                        f"```"
                    ),
                    inline=False
                )

            embed.set_footer(text="Menampilkan 5 transaksi terakhir")
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"```diff\n- {str(e)}```",
                color=COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        finally:
            self._release_interaction_lock(str(interaction.id))

class RegisterModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="📝 Pendaftaran GrowID")
        
        self.growid = discord.ui.TextInput(
            label="Masukkan GrowID Anda",
            placeholder="Contoh: GROW_ID",
            min_length=3,
            max_length=30
        )
        self.add_item(self.growid)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            balance_manager = BalanceManagerService(interaction.client)
            
            growid = str(self.growid.value).strip()
            if not growid:
                raise ValueError("GrowID tidak boleh kosong!")
                
            await balance_manager.register_user(
                str(interaction.user.id),
                growid
            )
            
            success_embed = discord.Embed(
                title="✅ Berhasil",
                description=f"GrowID `{growid}` berhasil didaftarkan!",
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
            option = discord.SelectOption(
                label=f"{product['name']} ({product['price']:,} WL)",
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
                raise ValueError("Produk tidak ditemukan")
                
            stock = await product_manager.get_stock_count(product['code'])
            if stock <= 0:
                raise ValueError("Maaf, stok produk ini sedang habis")
                
            embed = discord.Embed(
                title="🛍️ Konfirmasi Pembelian",
                description=(
                    f"```yml\n"
                    f"Produk: {product['name']}\n"
                    f"Harga: {product['price']:,} WL\n"
                    f"Stok: {stock} unit\n"
                    f"```"
                ),
                color=COLORS['info']
            )
            
            view = View(timeout=180)
            view.add_item(
                Button(
                    style=discord.ButtonStyle.success,
                    label="✅ Konfirmasi",
                    custom_id=f"confirm_purchase_{product['code']}"
                )
            )
            view.add_item(
                Button(
                    style=discord.ButtonStyle.danger,
                    label="❌ Batal",
                    custom_id="cancel_purchase"
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
            self.current_button_message: Optional[discord.Message] = None
            self.stock_manager = None
            self.initialized = True

    async def set_stock_manager(self, stock_manager):
        """Set stock manager untuk sinkronisasi"""
        self.stock_manager = stock_manager

    async def get_or_create_button_message(self) -> Optional[discord.Message]:
        """Ambil pesan tombol yang ada atau buat baru"""
        if not self.stock_channel_id:
            self.logger.error("ID channel stock belum dikonfigurasi!")
            return None

        channel = self.bot.get_channel(self.stock_channel_id)
        if not channel:
            self.logger.error(f"Channel stock dengan ID {self.stock_channel_id} tidak ditemukan")
            return None

        try:
            message_id = await self.cache_manager.get("live_buttons_message_id")
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    self.current_button_message = message
                    return message
                except discord.NotFound:
                    await self.cache_manager.delete("live_buttons_message_id")
                except Exception as e:
                    self.logger.error(f"Error mengambil pesan tombol: {e}")

            # Buat pesan baru dengan tombol
            view = ShopView(self.bot)
            message = await channel.send(view=view)
            
            self.current_button_message = message
            await self.cache_manager.set(
                "live_buttons_message_id", 
                message.id,
                expires_in=86400,
                permanent=True
            )
            return message

        except Exception as e:
            self.logger.error(f"Error in get_or_create_button_message: {e}")
            return None

    async def update_buttons(self) -> bool:
        """Update tombol-tombol"""
        try:
            message = await self.get_or_create_button_message()
            if not message:
                return False

            # Update view dengan tombol baru
            await message.edit(view=ShopView(self.bot))
            return True

        except Exception as e:
            self.logger.error(f"Error updating buttons: {e}")
            return False

    async def cleanup(self):
        """Bersihkan resources"""
        try:
            if self.current_button_message:
                embed = discord.Embed(
                    title="🛠️ Maintenance",
                    description="```diff\n- Toko sedang offline\n- Mohon tunggu maintenance selesai\n```",
                    color=COLORS['warning']
                )
                await self.current_button_message.edit(
                    embed=embed,
                    view=None
                )
        except Exception as e:
            self.logger.error(f"Error dalam cleanup: {e}")

class LiveButtonsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.button_manager = LiveButtonManager(bot)
        self.stock_manager = None
        self.logger = logging.getLogger("LiveButtonsCog")

    @commands.Cog.listener()
    async def on_ready(self):
        """Setup tombol ketika bot siap"""
        await self.button_manager.update_buttons()

    async def cog_load(self):
        """Setup saat cog dimuat"""
        self.logger.info("LiveButtonsCog loading...")
        # Dapatkan stock manager dari bot
        stock_cog = self.bot.get_cog('LiveStockCog')
        if stock_cog:
            self.stock_manager = stock_cog.stock_manager
        # Set up cross-references
        await self.button_manager.set_stock_manager(self.stock_manager)
        if self.stock_manager:
            await self.stock_manager.set_button_manager(self.button_manager)

    async def cog_unload(self):
        await self.button_manager.cleanup()
        self.logger.info("LiveButtonsCog unloaded")

async def setup(bot):
    if not hasattr(bot, 'live_buttons_loaded'):
        await bot.add_cog(LiveButtonsCog(bot))
        bot.live_buttons_loaded = True