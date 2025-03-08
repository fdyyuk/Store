"""
Balance Manager Service
Author: fdyyuk
Created at: 2025-03-07 18:04:56 UTC
Last Modified: 2025-03-08 05:39:58 UTC
"""

import logging
import asyncio
from typing import Dict, Optional, Union
from datetime import datetime

import discord
from discord.ext import commands

from .constants import (
    Balance,         # Update: menggunakan Balance class yang baru
    TransactionType,
    TransactionError,
    CURRENCY_RATES,
    MESSAGES,
    CACHE_TIMEOUT
)
from database import get_connection
from .base_handler import BaseLockHandler
from .cache_manager import CacheManager

class BalanceManagerService(BaseLockHandler):
    _instance = None
    _instance_lock = asyncio.Lock()

    def __new__(cls, bot):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, bot):
        if not self.initialized:
            super().__init__()  # Initialize BaseLockHandler
            self.bot = bot
            self.logger = logging.getLogger("BalanceManagerService")
            self.cache_manager = CacheManager()
            self.initialized = True

    async def get_growid(self, discord_id: str) -> Optional[str]:
        """Get GrowID for Discord user with proper locking and caching"""
        cache_key = f"growid_{discord_id}"
        cached = await self.cache_manager.get(cache_key)
        if cached:
            return cached

        lock = await self.acquire_lock(cache_key)
        if not lock:
            self.logger.warning(f"Failed to acquire lock for get_growid {discord_id}")
            return None

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT growid FROM user_growid WHERE discord_id = ? COLLATE binary",
                (str(discord_id),)
            )
            result = cursor.fetchone()
            
            if result:
                growid = result['growid']
                # Cache GrowID for 1 hour since it rarely changes
                await self.cache_manager.set(
                    cache_key, 
                    growid,
                    expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.LONG)
                )
                self.logger.info(f"Found GrowID for Discord ID {discord_id}: {growid}")
                return growid
            return None

        except Exception as e:
            self.logger.error(f"Error getting GrowID: {e}")
            return None
        finally:
            if conn:
                conn.close()
            self.release_lock(cache_key)

    async def get_user_by_growid(self, growid: str) -> Optional[str]:
        """Get Discord ID by GrowID with caching"""
        cache_key = f"discord_id_{growid}"
        cached = await self.cache_manager.get(cache_key)
        if cached:
            return cached

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT discord_id FROM user_growid WHERE growid = ? COLLATE binary",
                (growid,)
            )
            result = cursor.fetchone()
            
            if result:
                discord_id = result['discord_id']
                # Cache Discord ID for 1 hour
                await self.cache_manager.set(
                    cache_key, 
                    discord_id,
                    expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.LONG)
                )
                return discord_id
            return None

        except Exception as e:
            self.logger.error(f"Error getting Discord ID: {e}")
            return None
        finally:
            if conn:
                conn.close()

    async def register_user(self, discord_id: str, growid: str) -> bool:
        """Register user with proper locking"""
        if not growid or len(growid) < 3:
            raise ValueError(MESSAGES.ERROR['INVALID_GROWID'])
            
        lock = await self.acquire_lock(f"register_{discord_id}")
        if not lock:
            raise TransactionError(MESSAGES.ERROR['TRANSACTION_FAILED'])

        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Check for existing GrowID (case-sensitive)
            cursor.execute(
                "SELECT growid FROM users WHERE growid = ? COLLATE binary",
                (growid,)
            )
            existing = cursor.fetchone()
            if existing and existing['growid'] != growid:
                raise ValueError(MESSAGES.ERROR['GROWID_EXISTS'])
            
            # Begin transaction
            conn.execute("BEGIN TRANSACTION")
            
            # Create user if not exists with initial balance
            cursor.execute(
                """
                INSERT OR IGNORE INTO users (growid, balance_wl, balance_dl, balance_bgl) 
                VALUES (?, 0, 0, 0)
                """,
                (growid,)
            )
            
            # Link Discord ID to GrowID
            cursor.execute(
                """
                INSERT OR REPLACE INTO user_growid (discord_id, growid) 
                VALUES (?, ?)
                """,
                (str(discord_id), growid)
            )
            
            conn.commit()
            
            # Update caches
            await self.cache_manager.set(
                f"growid_{discord_id}", 
                growid,
                expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.LONG)
            )
            await self.cache_manager.set(
                f"discord_id_{growid}", 
                discord_id,
                expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.LONG)
            )
            await self.cache_manager.delete(f"balance_{growid}")
            
            self.logger.info(f"Registered Discord user {discord_id} with GrowID {growid}")
            return True

        except Exception as e:
            self.logger.error(f"Error registering user: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
            self.release_lock(f"register_{discord_id}")

    async def get_balance(self, growid: str) -> Optional[Balance]:
        """Get user balance with proper locking and caching"""
        cache_key = f"balance_{growid}"
        cached = await self.cache_manager.get(cache_key)
        if cached:
            # Convert cached dict to Balance object if needed
            if isinstance(cached, dict):
                return Balance(cached['wl'], cached['dl'], cached['bgl'])
            return cached

        lock = await self.acquire_lock(cache_key)
        if not lock:
            self.logger.warning(f"Failed to acquire lock for get_balance {growid}")
            return None

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT balance_wl, balance_dl, balance_bgl 
                FROM users 
                WHERE growid = ? COLLATE binary
                """,
                (growid,)
            )
            result = cursor.fetchone()
            
            if result:
                balance = Balance(
                    result['balance_wl'],
                    result['balance_dl'],
                    result['balance_bgl']
                )
                # Cache balance for 30 seconds since it changes frequently
                await self.cache_manager.set(
                    cache_key, 
                    balance,
                    expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.SHORT)
                )
                return balance
            return None

        except Exception as e:
            self.logger.error(f"Error getting balance: {e}")
            return None
        finally:
            if conn:
                conn.close()
            self.release_lock(cache_key)

    async def update_balance(
        self, 
        growid: str, 
        wl: int = 0, 
        dl: int = 0, 
        bgl: int = 0,
        details: str = "", 
        transaction_type: str = ""
    ) -> Optional[Balance]:
        """Update balance with proper locking and validation"""
        lock = await self.acquire_lock(f"balance_update_{growid}")
        if not lock:
            raise TransactionError(MESSAGES.ERROR['TRANSACTION_FAILED'])

        conn = None
        try:
            # Get current balance with retry
            current_balance = await self.get_balance(growid)
            if not current_balance:
                raise TransactionError(MESSAGES.ERROR['BALANCE_NOT_FOUND'])

            # Calculate new balance
            new_wl = max(0, current_balance.wl + wl)
            new_dl = max(0, current_balance.dl + dl)
            new_bgl = max(0, current_balance.bgl + bgl)
            
            # Create new balance object
            new_balance = Balance(new_wl, new_dl, new_bgl)
            
            # Validate new balance
            if not new_balance.validate():
                raise TransactionError(MESSAGES.ERROR['INVALID_AMOUNT'])

            # Additional validation for withdrawals
            if wl < 0 and abs(wl) > current_balance.wl:
                raise TransactionError(MESSAGES.ERROR['INSUFFICIENT_BALANCE'])
            if dl < 0 and abs(dl) > current_balance.dl:
                raise TransactionError(MESSAGES.ERROR['INSUFFICIENT_BALANCE'])
            if bgl < 0 and abs(bgl) > current_balance.bgl:
                raise TransactionError(MESSAGES.ERROR['INSUFFICIENT_BALANCE'])

            conn = get_connection()
            cursor = conn.cursor()
            
            try:
                # Begin transaction
                conn.execute("BEGIN TRANSACTION")
                
                # Update balance
                cursor.execute(
                    """
                    UPDATE users 
                    SET balance_wl = ?, balance_dl = ?, balance_bgl = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE growid = ? COLLATE binary
                    """,
                    (new_wl, new_dl, new_bgl, growid)
                )
                
                # Record transaction
                cursor.execute(
                    """
                    INSERT INTO transactions 
                    (growid, type, details, old_balance, new_balance, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        growid,
                        transaction_type,
                        details,
                        current_balance.format(),
                        new_balance.format()
                    )
                )
                
                conn.commit()
                
                # Update cache
                await self.cache_manager.set(
                    f"balance_{growid}", 
                    new_balance,
                    expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.SHORT)
                )
                
                # Invalidate transaction history cache
                await self.cache_manager.delete(f"trx_history_{growid}")
                
                self.logger.info(
                    f"Updated balance for {growid}: "
                    f"{current_balance.format()} -> {new_balance.format()}"
                )
                return new_balance

            except Exception as e:
                conn.rollback()
                raise TransactionError(str(e))

        except TransactionError:
            raise
        except Exception as e:
            self.logger.error(f"Error updating balance: {e}")
            raise TransactionError(MESSAGES.ERROR['TRANSACTION_FAILED'])
        finally:
            if conn:
                conn.close()
            self.release_lock(f"balance_update_{growid}")

    async def get_transaction_history(self, growid: str, limit: int = 10) -> list:
        """Get transaction history with caching"""
        cache_key = f"trx_history_{growid}"
        cached = await self.cache_manager.get(cache_key)
        if cached:
            return cached[:limit]  # Return only requested number of items

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM transactions 
                WHERE growid = ? COLLATE binary
                ORDER BY created_at DESC
                LIMIT ?
            """, (growid, limit))
            
            transactions = [dict(row) for row in cursor.fetchall()]
            
            # Cache for a short time since this changes frequently
            await self.cache_manager.set(
                cache_key, 
                transactions,
                expires_in=CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.SHORT)
            )
            
            return transactions

        except Exception as e:
            self.logger.error(f"Error getting transaction history: {e}")
            return []
        finally:
            if conn:
                conn.close()

class BalanceManagerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.balance_service = BalanceManagerService(bot)
        self.logger = logging.getLogger("BalanceManagerCog")

    async def cog_load(self):
        self.logger.info("BalanceManagerCog loading...")

    async def cog_unload(self):
        await self.balance_service.cleanup()
        self.logger.info("BalanceManagerCog unloaded")

async def setup(bot):
    if not hasattr(bot, 'balance_manager_loaded'):
        await bot.add_cog(BalanceManagerCog(bot))
        bot.balance_manager_loaded = True
        logging.info(
            f'BalanceManager cog loaded successfully at '
            f'{datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC'
        )