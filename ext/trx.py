"""
Transaction Manager Service
Author: fdyyuk
Created at: 2025-03-07 18:04:56 UTC
Last Modified: 2025-03-08 14:54:11 UTC

Dependencies:
- database.py: For database connections
- base_handler.py: For lock management
- cache_manager.py: For caching functionality
- product_manager.py: For product operations
- balance_manager.py: For balance operations
"""

import logging
import asyncio
from typing import Optional, Dict, List, Union, Callable, Any
from datetime import datetime

import discord
from discord.ext import commands

from .constants import (
    Status,
    TransactionType,
    Balance,
    TransactionError,
    MESSAGES,
    CACHE_TIMEOUT,
    COLORS,
    EVENTS,
    NOTIFICATION_CHANNELS
)
from database import get_connection
from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .product_manager import ProductManagerService
from .balance_manager import BalanceManagerService

class TransactionCallbackManager:
    """Callback manager untuk transaction service"""
    def __init__(self):
        self.callbacks = {
            'transaction_started': [],    # Saat transaksi dimulai
            'transaction_completed': [],  # Saat transaksi berhasil
            'transaction_failed': [],     # Saat transaksi gagal
            'purchase_completed': [],     # Khusus untuk pembelian
            'deposit_completed': [],      # Khusus untuk deposit
            'withdrawal_completed': [],   # Khusus untuk withdrawal
            'error': []                  # Untuk error handling
        }
    
    def register(self, event_type: str, callback: Callable):
        """Register callback untuk event tertentu"""
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
    
    async def trigger(self, event_type: str, *args: Any, **kwargs: Any):
        """Trigger semua callback untuk event tertentu"""
        if event_type in self.callbacks:
            for callback in self.callbacks[event_type]:
                try:
                    await callback(*args, **kwargs)
                except Exception as e:
                    logging.error(f"Error in {event_type} callback: {e}")

class TransactionResponse:
    """Standarisasi response dari transaction service"""
    def __init__(
        self,
        success: bool,
        transaction_type: str = "",
        data: Any = None,
        message: str = "",
        error: str = "",
        product_response: Any = None,
        balance_response: Any = None
    ):
        self.success = success
        self.transaction_type = transaction_type
        self.data = data
        self.message = message
        self.error = error
        self.product_data = product_response
        self.balance_data = balance_response
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'transaction_type': self.transaction_type,
            'data': self.data,
            'message': self.message,
            'error': self.error,
            'product_data': self.product_data,
            'balance_data': self.balance_data,
            'timestamp': self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    @classmethod
    def success(cls, transaction_type: str, data: Any = None, 
                message: str = "", product_response: Any = None, 
                balance_response: Any = None) -> 'TransactionResponse':
        return cls(True, transaction_type, data, message, 
                  product_response=product_response,
                  balance_response=balance_response)
    
    @classmethod
    def error(cls, error: str, message: str = "") -> 'TransactionResponse':
        return cls(False, "", None, message, error)

class TransactionManager(BaseLockHandler):
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
            self.logger = logging.getLogger("TransactionManager")
            self.cache_manager = CacheManager()
            self.product_manager = ProductManagerService(bot)
            self.balance_manager = BalanceManagerService(bot)
            self.callback_manager = TransactionCallbackManager()
            self.setup_default_callbacks()
            self.initialized = True
    
    def setup_default_callbacks(self):
        """Setup default callbacks untuk notifikasi"""
        
        async def notify_transaction_completed(transaction_type: str, **data):
            """Notifikasi untuk transaksi yang berhasil"""
            channel_id = NOTIFICATION_CHANNELS.get('transactions')
            if channel := self.bot.get_channel(channel_id):
                embed = discord.Embed(
                    title=f"{transaction_type.title()} Completed",
                    description="Transaction processed successfully",
                    color=COLORS.SUCCESS
                )
                for key, value in data.items():
                    embed.add_field(name=key.replace('_', ' ').title(), 
                                  value=str(value))
                await channel.send(embed=embed)
        
        async def notify_transaction_failed(error: str, **data):
            """Notifikasi untuk transaksi yang gagal"""
            channel_id = NOTIFICATION_CHANNELS.get('error_logs')
            if channel := self.bot.get_channel(channel_id):
                embed = discord.Embed(
                    title="Transaction Failed",
                    description=error,
                    color=COLORS.ERROR
                )
                for key, value in data.items():
                    embed.add_field(name=key.replace('_', ' ').title(), 
                                  value=str(value))
                await channel.send(embed=embed)
        
        # Register default callbacks
        self.callback_manager.register('transaction_completed', 
                                     notify_transaction_completed)
        self.callback_manager.register('transaction_failed', 
                                     notify_transaction_failed)

    async def process_purchase(
        self, 
        buyer_id: str, 
        product_code: str, 
        quantity: int = 1
    ) -> TransactionResponse:
        """Process purchase dengan proper coordination"""
        if quantity < 1:
            return TransactionResponse.error(MESSAGES.ERROR['INVALID_AMOUNT'])

        lock = await self.acquire_lock(f"purchase_{buyer_id}_{product_code}")
        if not lock:
            return TransactionResponse.error(MESSAGES.ERROR['LOCK_ACQUISITION_FAILED'])

        try:
            # Notify transaction started
            await self.callback_manager.trigger('transaction_started',
                buyer_id=buyer_id,
                product_code=product_code,
                quantity=quantity
            )

            # Get buyer's GrowID
            growid_response = await self.balance_manager.get_growid(buyer_id)
            if not growid_response.success:
                return TransactionResponse.error(growid_response.error)
            growid = growid_response.data

            # Get product details
            product_response = await self.product_manager.get_product(product_code)
            if not product_response.success:
                return TransactionResponse.error(product_response.error)
            product = product_response.data

            # Get available stock
            stock_response = await self.product_manager.get_available_stock(
                product_code, 
                quantity
            )
            if not stock_response.success:
                return TransactionResponse.error(stock_response.error)
            available_stock = stock_response.data

            # Calculate total price
            total_price = product['price'] * quantity

            # Get and verify balance
            balance_response = await self.balance_manager.get_balance(growid)
            if not balance_response.success:
                return TransactionResponse.error(balance_response.error)
            current_balance = balance_response.data

            if total_price > current_balance.total_wl():
                return TransactionResponse.error(MESSAGES.ERROR['INSUFFICIENT_BALANCE'])

            # Update stock status via ProductManager
            stock_update_response = await self.product_manager.update_stock_status(
                product_code,
                [item['id'] for item in available_stock[:quantity]],
                Status.SOLD.value,
                buyer_id
            )
            if not stock_update_response.success:
                return TransactionResponse.error(stock_update_response.error)

            # Update balance via BalanceManager
            balance_update_response = await self.balance_manager.update_balance(
                growid=growid,
                wl=-total_price,
                details=f"Purchase {quantity}x {product['name']}",
                transaction_type=TransactionType.PURCHASE.value
            )
            if not balance_update_response.success:
                # Rollback stock status if balance update fails
                await self.product_manager.update_stock_status(
                    product_code,
                    [item['id'] for item in available_stock[:quantity]],
                    Status.AVAILABLE.value,
                    None
                )
                return TransactionResponse.error(balance_update_response.error)

            # Prepare content list
            content_list = [item['content'] for item in available_stock[:quantity]]

            # Trigger completion callbacks
            await self.callback_manager.trigger(
                'purchase_completed',
                buyer_id=buyer_id,
                growid=growid,
                product_code=product_code,
                quantity=quantity,
                total_price=total_price,
                new_balance=balance_update_response.data
            )

            await self.callback_manager.trigger(
                'transaction_completed',
                transaction_type='purchase',
                buyer=growid,
                product=product['name'],
                quantity=quantity,
                total=total_price
            )

            return TransactionResponse.success(
                transaction_type='purchase',
                data={
                    'content': content_list,
                    'total_paid': total_price
                },
                message=(
                    f"{MESSAGES.SUCCESS['PURCHASE']}\n"
                    f"Product: {product['name']}\n"
                    f"Quantity: {quantity}x\n"
                    f"Total paid: {total_price:,} WL\n"
                    f"New balance: {balance_update_response.data.format()}"
                ),
                product_response=product_response,
                balance_response=balance_update_response
            )

        except Exception as e:
            self.logger.error(f"Error processing purchase: {e}")
            await self.callback_manager.trigger(
                'transaction_failed',
                error=str(e),
                buyer_id=buyer_id,
                product_code=product_code
            )
            return TransactionResponse.error(MESSAGES.ERROR['TRANSACTION_FAILED'])
        finally:
            self.release_lock(f"purchase_{buyer_id}_{product_code}")

    async def process_deposit(
        self, 
        user_id: str, 
        wl: int = 0, 
        dl: int = 0, 
        bgl: int = 0,
        admin_id: Optional[str] = None
    ) -> TransactionResponse:
        """Process deposit dengan proper coordination"""
        if wl < 0 or dl < 0 or bgl < 0:
            return TransactionResponse.error(MESSAGES.ERROR['INVALID_AMOUNT'])

        lock = await self.acquire_lock(f"deposit_{user_id}")
        if not lock:
            return TransactionResponse.error(MESSAGES.ERROR['LOCK_ACQUISITION_FAILED'])

        try:
            await self.callback_manager.trigger(
                'transaction_started',
                transaction_type='deposit',
                user_id=user_id,
                wl=wl,
                dl=dl,
                bgl=bgl
            )

            # Get user's GrowID
            growid_response = await self.balance_manager.get_growid(user_id)
            if not growid_response.success:
                return TransactionResponse.error(growid_response.error)
            growid = growid_response.data

            # Calculate total deposit
            total_wl = wl + (dl * 100) + (bgl * 10000)
            if total_wl <= 0:
                return TransactionResponse.error(MESSAGES.ERROR['INVALID_AMOUNT'])

            # Format deposit details
            details = f"Deposit: {wl:,} WL"
            if dl > 0:
                details += f", {dl:,} DL"
            if bgl > 0:
                details += f", {bgl:,} BGL"
            if admin_id:
                admin_name = self.bot.get_user(int(admin_id))
                details += f" (by {admin_name})"

            # Process deposit via BalanceManager
            balance_response = await self.balance_manager.update_balance(
                growid=growid,
                wl=wl,
                dl=dl,
                bgl=bgl,
                details=details,
                transaction_type=TransactionType.DEPOSIT.value
            )
            if not balance_response.success:
                return TransactionResponse.error(balance_response.error)

            # Trigger completion callbacks
            await self.callback_manager.trigger(
                'deposit_completed',
                user_id=user_id,
                growid=growid,
                total_wl=total_wl,
                new_balance=balance_response.data
            )

            await self.callback_manager.trigger(
                'transaction_completed',
                transaction_type='deposit',
                user=growid,
                amount=f"{total_wl:,} WL"
            )

            return TransactionResponse.success(
                transaction_type='deposit',
                data={'total_deposited': total_wl},
                message=(
                    f"{MESSAGES.SUCCESS['BALANCE_UPDATE']}\n"
                    f"Deposited:\n"
                    f"{wl:,} WL{f', {dl:,} DL' if dl > 0 else ''}"
                    f"{f', {bgl:,} BGL' if bgl > 0 else ''}\n"
                    f"New balance: {balance_response.data.format()}"
                ),
                balance_response=balance_response
            )

        except Exception as e:
            self.logger.error(f"Error processing deposit: {e}")
            await self.callback_manager.trigger(
                'transaction_failed',
                error=str(e),
                user_id=user_id
            )
            return TransactionResponse.error(MESSAGES.ERROR['TRANSACTION_FAILED'])
        finally:
            self.release_lock(f"deposit_{user_id}")
    async def process_withdrawal(
        self, 
        user_id: str, 
        wl: int = 0, 
        dl: int = 0, 
        bgl: int = 0,
        admin_id: Optional[str] = None
    ) -> TransactionResponse:
        """Process withdrawal dengan proper coordination"""
        if wl < 0 or dl < 0 or bgl < 0:
            return TransactionResponse.error(MESSAGES.ERROR['INVALID_AMOUNT'])

        lock = await self.acquire_lock(f"withdrawal_{user_id}")
        if not lock:
            return TransactionResponse.error(MESSAGES.ERROR['LOCK_ACQUISITION_FAILED'])

        try:
            await self.callback_manager.trigger(
                'transaction_started',
                transaction_type='withdrawal',
                user_id=user_id,
                wl=wl,
                dl=dl,
                bgl=bgl
            )

            # Get user's GrowID
            growid_response = await self.balance_manager.get_growid(user_id)
            if not growid_response.success:
                return TransactionResponse.error(growid_response.error)
            growid = growid_response.data

            # Get current balance
            balance_response = await self.balance_manager.get_balance(growid)
            if not balance_response.success:
                return TransactionResponse.error(balance_response.error)
            current_balance = balance_response.data

            # Calculate total withdrawal
            total_wl = wl + (dl * 100) + (bgl * 10000)
            if total_wl <= 0:
                return TransactionResponse.error(MESSAGES.ERROR['INVALID_AMOUNT'])

            # Check if sufficient balance
            if total_wl > current_balance.total_wl():
                return TransactionResponse.error(MESSAGES.ERROR['INSUFFICIENT_BALANCE'])

            # Format withdrawal details
            details = f"Withdrawal: {wl:,} WL"
            if dl > 0:
                details += f", {dl:,} DL"
            if bgl > 0:
                details += f", {bgl:,} BGL"
            if admin_id:
                admin_name = self.bot.get_user(int(admin_id))
                details += f" (by {admin_name})"

            # Process withdrawal via BalanceManager
            balance_response = await self.balance_manager.update_balance(
                growid=growid,
                wl=-wl,
                dl=-dl,
                bgl=-bgl,
                details=details,
                transaction_type=TransactionType.WITHDRAWAL.value
            )
            if not balance_response.success:
                return TransactionResponse.error(balance_response.error)

            # Trigger completion callbacks
            await self.callback_manager.trigger(
                'withdrawal_completed',
                user_id=user_id,
                growid=growid,
                total_wl=total_wl,
                new_balance=balance_response.data
            )

            await self.callback_manager.trigger(
                'transaction_completed',
                transaction_type='withdrawal',
                user=growid,
                amount=f"{total_wl:,} WL"
            )

            return TransactionResponse.success(
                transaction_type='withdrawal',
                data={'total_withdrawn': total_wl},
                message=(
                    f"{MESSAGES.SUCCESS['BALANCE_UPDATE']}\n"
                    f"Withdrawn:\n"
                    f"{wl:,} WL{f', {dl:,} DL' if dl > 0 else ''}"
                    f"{f', {bgl:,} BGL' if bgl > 0 else ''}\n"
                    f"New balance: {balance_response.data.format()}"
                ),
                balance_response=balance_response
            )

        except Exception as e:
            self.logger.error(f"Error processing withdrawal: {e}")
            await self.callback_manager.trigger(
                'transaction_failed',
                error=str(e),
                user_id=user_id
            )
            return TransactionResponse.error(MESSAGES.ERROR['TRANSACTION_FAILED'])
        finally:
            self.release_lock(f"withdrawal_{user_id}")

class TransactionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.trx_manager = TransactionManager(bot)
        self.logger = logging.getLogger("TransactionCog")

    async def cog_load(self):
        """Setup saat cog di-load"""
        self.logger.info("TransactionCog loading...")
        
        # Setup additional monitoring callbacks
        await self.setup_monitoring()

    async def cog_unload(self):
        """Cleanup saat cog di-unload"""
        self.logger.info("TransactionCog unloaded")

    async def setup_monitoring(self):
        """Setup monitoring callbacks"""
        
        async def monitor_large_transactions(**data):
            """Monitor transaksi dalam jumlah besar"""
            if 'total_wl' in data and data['total_wl'] > 100000:  # 100K WL threshold
                channel_id = NOTIFICATION_CHANNELS.get('admin_logs')
                if channel := self.bot.get_channel(channel_id):
                    embed = discord.Embed(
                        title="Large Transaction Alert",
                        description="Transaction above 100K WL detected",
                        color=COLORS.WARNING
                    )
                    for key, value in data.items():
                        embed.add_field(
                            name=key.replace('_', ' ').title(),
                            value=str(value)
                        )
                    await channel.send(embed=embed)
        
        async def monitor_failed_transactions(error: str, **data):
            """Monitor transaksi yang gagal"""
            channel_id = NOTIFICATION_CHANNELS.get('error_logs')
            if channel := self.bot.get_channel(channel_id):
                embed = discord.Embed(
                    title="Transaction Failed",
                    description=error,
                    color=COLORS.ERROR
                )
                for key, value in data.items():
                    embed.add_field(
                        name=key.replace('_', ' ').title(),
                        value=str(value)
                    )
                await channel.send(embed=embed)
        
        async def monitor_quick_transactions(**data):
            """Monitor transaksi yang terlalu cepat dari user yang sama"""
            # Implementation of rate limiting monitoring
            pass

        # Register monitoring callbacks
        self.trx_manager.callback_manager.register(
            'transaction_completed',
            monitor_large_transactions
        )
        self.trx_manager.callback_manager.register(
            'transaction_failed',
            monitor_failed_transactions
        )

async def setup(bot):
    """Setup function untuk menambahkan cog ke bot"""
    if not hasattr(bot, 'transaction_manager_loaded'):
        # Verify dependencies dulu
        product_manager = ProductManagerService(bot)
        balance_manager = BalanceManagerService(bot)
        
        # Check if required managers are loaded
        if not hasattr(bot, 'product_manager_loaded'):
            raise Exception("ProductManager must be loaded before TransactionManager")
        if not hasattr(bot, 'balance_manager_loaded'):
            raise Exception("BalanceManager must be loaded before TransactionManager")
            
        # Add cog
        cog = TransactionCog(bot)
        await bot.add_cog(cog)
        bot.transaction_manager_loaded = True
        
        logging.info(
            f'Transaction Manager cog loaded successfully at '
            f'{datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC'
        )