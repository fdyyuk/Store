"""
Live Buttons Manager with Shop Integration
Author: fdyyuk
Created at: 2025-03-07 22:35:08 UTC
Last Modified: 2025-03-08 16:13:14 UTC

Dependencies:
- ext.product_manager: For product operations
- ext.balance_manager: For balance operations
- ext.trx: For transaction operations
- ext.admin_service: For maintenance mode
- ext.constants: For configuration and responses
"""

import discord
from discord.ext import commands, tasks
from discord import ui
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict

from .constants import (
    COLORS,
    MESSAGES,
    BUTTON_IDS,
    CACHE_TIMEOUT,
    Stock,
    Status,
    CURRENCY_RATES,
    UPDATE_INTERVAL
)


from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .product_manager import ProductManagerService
from .balance_manager import BalanceManagerService
from .trx import TransactionManager
from .admin_service import AdminService

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
    def __init__(self, products: List[Dict], balance_service, product_service, trx_manager):
        self.products_cache = {p['code']: p for p in products}
        self.balance_service = balance_service
        self.product_service = product_service
        self.trx_manager = trx_manager
        
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
            product_response = await self.product_service.get_product(selected_code)
            if not product_response.success:
                raise ValueError(product_response.error)
                
            selected_product = product_response.data
            
            # Verifikasi stock realtime
            stock_response = await self.product_service.get_stock_count(selected_code)
            if not stock_response.success:
                raise ValueError(stock_response.error)
                
            current_stock = stock_response.data
            if current_stock <= 0:
                raise ValueError(MESSAGES.ERROR['OUT_OF_STOCK'])
            
            # Verifikasi user balance
            growid_response = await self.balance_service.get_growid(str(interaction.user.id))
            if not growid_response.success:
                raise ValueError(growid_response.error)
            
            growid = growid_response.data
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
            balance_service = BalanceManagerService(interaction.client)
            
            growid = str(self.growid.value).strip().upper()
            if not growid or len(growid) < 3:
                raise ValueError(MESSAGES.ERROR['INVALID_GROWID'])
            
            # Register user with proper response handling
            register_response = await balance_service.register_user(
                str(interaction.user.id),
                growid
            )
            
            if not register_response.success:
                raise ValueError(register_response.error)
            
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
        # Initialize services
        self.balance_service = BalanceManagerService(bot)
        self.product_service = ProductManagerService(bot)
        self.trx_manager = TransactionManager(bot)
        self.admin_service = AdminService(bot)
        self.cache_manager = CacheManager()
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
            # Check maintenance mode
            if await self.admin_service.is_maintenance_mode():
                raise ValueError(MESSAGES.INFO['MAINTENANCE'])

            growid_response = await self.balance_service.get_growid(str(interaction.user.id))
            if growid_response.success and growid_response.data:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Sudah Terdaftar",
                        description=f"Anda sudah terdaftar dengan GrowID: `{growid_response.data}`",
                        color=COLORS.ERROR
                    ),
                    ephemeral=True
                )
                return

            modal = RegisterModal()
            await interaction.response.send_modal(modal)

        except ValueError as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Error",
                        description=str(e),
                        color=COLORS.ERROR
                    ),
                    ephemeral=True
                )
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
            
            # Check maintenance mode
            if await self.admin_service.is_maintenance_mode():
                raise ValueError(MESSAGES.INFO['MAINTENANCE'])
            
            growid_response = await self.balance_service.get_growid(str(interaction.user.id))
            if not growid_response.success:
                raise ValueError(growid_response.error)
                
            growid = growid_response.data
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            balance_response = await self.balance_service.get_balance(growid)
            if not balance_response.success:
                raise ValueError(balance_response.error)
                
            balance = balance_response.data

            # Format balance untuk display
            balance_wls = balance.total_wl()
            display_balance = self._format_currency(balance_wls)

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
            trx_response = await self.trx_manager.get_transaction_history(growid, limit=3)
            if trx_response.success and trx_response.data:
                transactions = trx_response.data
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

    def _format_currency(self, amount: int) -> str:
        """Format currency amount with proper denominations"""
        try:
            if amount >= CURRENCY_RATES['BGL']:
                return f"{amount/CURRENCY_RATES['BGL']:.1f} BGL"
            elif amount >= CURRENCY_RATES['DL']:
                return f"{amount/CURRENCY_RATES['DL']:.0f} DL"
            return f"{int(amount)} WL"
        except Exception:
            return "Invalid Amount"

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
            
            # Check maintenance mode
            if await self.admin_service.is_maintenance_mode():
                raise ValueError(MESSAGES.INFO['MAINTENANCE'])
            
            # Try to get from cache first
            cache_key = 'world_info'
            world_info = await self.cache_manager.get(cache_key)
            
            if not world_info:
                world_response = await self.product_service.get_world_info()
                if not world_response.success:
                    raise ValueError(world_response.error)
                    
                world_info = world_response.data
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

        except ValueError as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                color=COLORS.ERROR
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
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
            
            # Check maintenance mode
            if await self.admin_service.is_maintenance_mode():
                raise ValueError(MESSAGES.INFO['MAINTENANCE'])
            
            growid_response = await self.balance_service.get_growid(str(interaction.user.id))
            if not growid_response.success:
                raise ValueError(growid_response.error)
                
            growid = growid_response.data
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            # Get products with proper response handling
            product_response = await self.product_service.get_all_products()
            if not product_response.success:
                raise ValueError(product_response.error)
                
            products = product_response.data
            available_products = []
            
            for product in products:
                stock_response = await self.product_service.get_stock_count(product['code'])
                if stock_response.success and stock_response.data > 0:
                    product['stock'] = stock_response.data
                    available_products.append(product)

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
                price = float(product['price'])
                price_display = self._format_currency(price)
                    
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
                self.balance_service,
                self.product_service,
                self.trx_manager
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
            
            # Check maintenance mode
            if await self.admin_service.is_maintenance_mode():
                raise ValueError(MESSAGES.INFO['MAINTENANCE'])
            
            growid_response = await self.balance_service.get_growid(str(interaction.user.id))
            if not growid_response.success:
                raise ValueError(growid_response.error)
                
            growid = growid_response.data
            if not growid:
                raise ValueError(MESSAGES.ERROR['NOT_REGISTERED'])

            trx_response = await self.trx_manager.get_transaction_history(growid, limit=5)
            if not trx_response.success:
                raise ValueError(trx_response.error)
                
            transactions = trx_response.data
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
                    TransactionType.WITHDRAWAL.value: "💸",
                    TransactionType.ADMIN_ADD.value: "⚡",
                    TransactionType.ADMIN_REMOVE.value: "🔸"
                }
                emoji = emoji_map.get(trx['type'], "❓")
                
                # Format timestamp
                timestamp = datetime.fromisoformat(trx['created_at'].replace('Z', '+00:00'))
                
                # Calculate balance change
                old_balance = Balance.from_string(trx['old_balance'])
                new_balance = Balance.from_string(trx['new_balance'])
                balance_change = new_balance.total_wl() - old_balance.total_wl()
                
                # Format balance change
                change_display = self._format_currency(abs(balance_change))
                change_prefix = "+" if balance_change >= 0 else "-"
                
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
            self.admin_service = AdminService(bot)
            self.stock_channel_id = int(self.bot.config.get('id_live_stock', 0))
            self.current_message: Optional[discord.Message] = None
            self.stock_manager = None
            self.initialized = True

    async def set_stock_manager(self, stock_manager):
        """Set stock manager untuk integrasi"""
        self.stock_manager = stock_manager
        # Set referensi balik ke stock manager
        await stock_manager.set_button_manager(self)
        # Force update setelah set stock manager
        await self.force_update()

    async def ensure_stock_manager(self, max_retries=5) -> bool:
        """Memastikan stock manager tersedia"""
        retries = 0
        while not self.stock_manager and retries < max_retries:
            self.logger.info(f"Waiting for StockManager... (attempt {retries + 1}/{max_retries})")
            await asyncio.sleep(1)
            retries += 1
            
        if not self.stock_manager:
            self.logger.error("StockManager not available after max retries")
            return False
        return True

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
            # Check maintenance mode first
            is_maintenance = await self.admin_service.is_maintenance_mode()
            
            # Coba dapatkan message dari cache
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
                    self.logger.warning("Cached message not found, creating new one...")
                except Exception as e:
                    self.logger.error(f"Error mengambil pesan: {e}")

            # Tunggu stock manager jika belum tersedia
            await self.ensure_stock_manager()

            # Buat pesan baru dengan embed dan view
            if is_maintenance:
                embed = discord.Embed(
                    title="🔧 Maintenance Mode",
                    description=MESSAGES.INFO['MAINTENANCE'],
                    color=COLORS.WARNING
                )
                message = await channel.send(embed=embed)
            else:
                if self.stock_manager:
                    embed = await self.stock_manager.create_stock_embed()
                else:
                    embed = discord.Embed(
                        title="🏪 Live Stock",
                        description=MESSAGES.INFO['INITIALIZING'],
                        color=COLORS.WARNING
                    )
                    
                view = ShopView(self.bot)
                message = await channel.send(embed=embed, view=view)
            
            self.current_message = message
            if self.stock_manager:
                self.stock_manager.current_stock_message = message
                # Trigger immediate update
                await self.stock_manager.update_stock_display()
                
            await self.cache_manager.set(
                "live_stock_message_id",
                message.id,
                expires_in=CACHE_TIMEOUT.PERMANENT
            )
            return message

        except Exception as e:
            self.logger.error(f"Error in get_or_create_message: {e}")
            return None

    async def force_update(self) -> bool:
        """Force update stock display and buttons"""
        try:
            if not self.current_message:
                self.current_message = await self.get_or_create_message()
                
            if not self.current_message:
                return False

            # Check maintenance mode
            is_maintenance = await self.admin_service.is_maintenance_mode()
            if is_maintenance:
                embed = discord.Embed(
                    title="🔧 Maintenance Mode",
                    description=MESSAGES.INFO['MAINTENANCE'],
                    color=COLORS.WARNING
                )
                await self.current_message.edit(embed=embed, view=None)
                return True

            if self.stock_manager:
                await self.stock_manager.update_stock_display()
            
            view = ShopView(self.bot)
            await self.current_message.edit(view=view)
            return True

        except Exception as e:
            self.logger.error(f"Error in force update: {e}")
            return False

    async def update_buttons(self) -> bool:
        """Update buttons display"""
        try:
            if not self.current_message:
                self.current_message = await self.get_or_create_message()
                
            if not self.current_message:
                return False

            # Check maintenance mode
            is_maintenance = await self.admin_service.is_maintenance_mode()
            if is_maintenance:
                embed = discord.Embed(
                    title="🔧 Maintenance Mode",
                    description=MESSAGES.INFO['MAINTENANCE'],
                    color=COLORS.WARNING
                )
                await self.current_message.edit(embed=embed, view=None)
                return True

            view = ShopView(self.bot)
            await self.current_message.edit(view=view)
            return True

        except discord.NotFound:
            self.logger.warning("Message not found, attempting recovery...")
            self.current_message = None
            return await self.force_update()
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
                
            # Clear caches
            patterns = [
                'live_stock_message_id',
                'world_info',
                'available_products'
            ]
            for pattern in patterns:
                await self.cache_manager.delete_pattern(pattern)
                
            self.logger.info("LiveButtonManager cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error in cleanup: {e}")

class LiveButtonsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.button_manager = LiveButtonManager(bot)
        self.stock_manager = None
        self.logger = logging.getLogger("LiveButtonsCog")
        self.check_display.start()

    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.check_display.cancel()
        asyncio.create_task(self.button_manager.cleanup())
        self.logger.info("LiveButtonsCog unloaded")

    @tasks.loop(minutes=5)
    async def check_display(self):
        """Periodically check if display is working"""
        try:
            if not self.button_manager.current_message:
                self.logger.warning("Stock message not found, attempting recovery...")
                await self.button_manager.force_update()
        except Exception as e:
            self.logger.error(f"Error in display check: {e}")

    @check_display.before_loop
    async def before_check_display(self):
        """Wait until bot is ready before starting the loop"""
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        """Setup buttons when bot is ready"""
        retries = 0
        max_retries = 5
        while not self.stock_manager and retries < max_retries:
            self.logger.info(f"Attempting to get StockManager (attempt {retries + 1}/{max_retries})")
            stock_cog = self.bot.get_cog('LiveStockCog')
            if stock_cog:
                self.stock_manager = stock_cog.stock_manager
                await self.button_manager.set_stock_manager(self.stock_manager)
                break
            retries += 1
            await asyncio.sleep(1)
        
        if not self.stock_manager:
            self.logger.error("Failed to get StockManager after max retries")
        
        await self.button_manager.update_buttons()

    async def cog_load(self):
        """Setup when cog is loaded"""
        self.logger.info("LiveButtonsCog loading...")
        stock_cog = self.bot.get_cog('LiveStockCog')
        if stock_cog:
            self.stock_manager = stock_cog.stock_manager
            await self.button_manager.set_stock_manager(self.stock_manager)

async def setup(bot):
    """Setup LiveButtonsCog dengan proper error handling"""
    if not hasattr(bot, 'live_buttons_loaded'):
        try:
            # Verify all required dependencies
            required_dependencies = [
                'product_manager_loaded',
                'balance_manager_loaded',
                'transaction_manager_loaded',
                'admin_service_loaded',
                'live_stock_loaded'
            ]
            
            for dependency in required_dependencies:
                if not hasattr(bot, dependency):
                    raise Exception(MESSAGES.ERROR['MISSING_DEPENDENCY'].format(dependency))

            # Pastikan LiveStockCog sudah di-load
            stock_cog = bot.get_cog('LiveStockCog')
            if not stock_cog:
                logging.warning("LiveStockCog not found, attempting to load...")
                try:
                    await bot.load_extension('ext.live_stock')
                    await asyncio.sleep(1)  # Beri waktu untuk inisialisasi
                except Exception as e:
                    logging.error(f"Failed to load LiveStockCog: {e}")
                    raise

            await bot.add_cog(LiveButtonsCog(bot))
            bot.live_buttons_loaded = True
            logging.info(MESSAGES.SUCCESS['COG_LOADED'].format('LiveButtons'))
            
        except Exception as e:
            logging.error(f"Failed to load LiveButtonsCog: {e}")
            raise