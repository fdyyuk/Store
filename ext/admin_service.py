"""
Admin Service for Store Management
Author: fdyyuk
Created at: 2025-03-08 16:54:50 UTC
Last Modified: 2025-03-08 16:54:50 UTC

Dependencies:
- base_handler.py: For lock management
- cache_manager.py: For caching functionality 
- constants.py: For configuration and responses
"""

import logging
import asyncio
from typing import Optional, Dict, List, Callable, Any
from datetime import datetime

import discord
from discord.ext import commands

from .constants import (
    CACHE_TIMEOUT,
    MESSAGES,
    COLORS,
    NOTIFICATION_CHANNELS
)
from .base_handler import BaseLockHandler
from .cache_manager import CacheManager
from .response import Response

class AdminCallbackManager:
    """Callback manager untuk admin service"""
    def __init__(self):
        self.callbacks = {
            'maintenance_enabled': [],     # Saat maintenance diaktifkan
            'maintenance_disabled': [],    # Saat maintenance dinonaktifkan
            'maintenance_checked': [],     # Saat status maintenance dicek
            'admin_action': [],           # Saat admin melakukan aksi
            'error': []                   # Saat terjadi error
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

class AdminService(BaseLockHandler):
    """Service untuk mengelola admin functions termasuk maintenance mode"""
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
            self.logger = logging.getLogger("AdminService")
            self.cache_manager = CacheManager()
            self.callback_manager = AdminCallbackManager()
            self.maintenance_key = "maintenance_mode"
            self.setup_default_callbacks()
            self.initialized = True

    def setup_default_callbacks(self):
        """Setup default callbacks untuk notifikasi"""
        
        async def notify_maintenance_enabled(reason: str, admin: str):
            """Callback untuk notifikasi maintenance aktif"""
            channel_id = NOTIFICATION_CHANNELS.get('admin_logs')
            if channel := self.bot.get_channel(channel_id):
                embed = discord.Embed(
                    title="🔧 Maintenance Mode Enabled",
                    description=f"System entered maintenance mode",
                    color=COLORS.WARNING,
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Reason", value=reason)
                embed.add_field(name="Enabled By", value=admin)
                await channel.send(embed=embed)

        async def notify_maintenance_disabled(admin: str):
            """Callback untuk notifikasi maintenance nonaktif"""
            channel_id = NOTIFICATION_CHANNELS.get('admin_logs')
            if channel := self.bot.get_channel(channel_id):
                embed = discord.Embed(
                    title="✅ Maintenance Mode Disabled",
                    description="System maintenance completed",
                    color=COLORS.SUCCESS,
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Disabled By", value=admin)
                await channel.send(embed=embed)

        async def log_maintenance_check(checker: str, status: bool):
            """Log setiap pengecekan status maintenance"""
            self.logger.info(
                f"Maintenance status checked by {checker}: "
                f"{'Active' if status else 'Inactive'}"
            )

        # Register default callbacks
        self.callback_manager.register('maintenance_enabled', notify_maintenance_enabled)
        self.callback_manager.register('maintenance_disabled', notify_maintenance_disabled)
        self.callback_manager.register('maintenance_checked', log_maintenance_check)

    async def set_maintenance_mode(self, enabled: bool, reason: str = None, admin: str = None) -> Response:
        """Enable/disable maintenance mode"""
        lock = await self.acquire_lock(self.maintenance_key)
        if not lock:
            return Response(False, error=MESSAGES.ERROR['LOCK_ACQUISITION_FAILED'])

        try:
            maintenance_data = {
                'enabled': enabled,
                'reason': reason or "System maintenance",
                'timestamp': datetime.utcnow().isoformat(),
                'updated_by': admin
            }
            
            # Set cache dengan waktu permanen
            await self.cache_manager.set(
                self.maintenance_key,
                maintenance_data,
                expires_in=CACHE_TIMEOUT.PERMANENT
            )

            # Trigger callbacks
            if enabled:
                await self.callback_manager.trigger(
                    'maintenance_enabled',
                    reason=maintenance_data['reason'],
                    admin=admin
                )
            else:
                await self.callback_manager.trigger(
                    'maintenance_disabled',
                    admin=admin
                )

            # Update live displays jika ada
            if hasattr(self.bot, 'live_buttons_loaded'):
                button_cog = self.bot.get_cog('LiveButtonsCog')
                if button_cog and button_cog.button_manager:
                    await button_cog.button_manager.force_update()

            return Response(True, data=maintenance_data)

        except Exception as e:
            self.logger.error(f"Error setting maintenance mode: {e}")
            await self.callback_manager.trigger('error', 'set_maintenance_mode', str(e))
            return Response(False, error=str(e))
        finally:
            self.release_lock(self.maintenance_key)

    async def get_maintenance_info(self) -> Response:
        """Get current maintenance status"""
        try:
            maintenance_data = await self.cache_manager.get(self.maintenance_key)
            if not maintenance_data:
                maintenance_data = {
                    'enabled': False,
                    'reason': None,
                    'timestamp': None,
                    'updated_by': None
                }
            return Response(True, data=maintenance_data)
        except Exception as e:
            self.logger.error(f"Error getting maintenance status: {e}")
            await self.callback_manager.trigger('error', 'get_maintenance_info', str(e))
            return Response(False, error=str(e))

    async def is_maintenance_mode(self) -> bool:
        """Check if system is in maintenance mode"""
        try:
            status = await self.get_maintenance_info()
            is_maintenance = status.success and status.data.get('enabled', False)
            
            # Trigger status check callback
            await self.callback_manager.trigger(
                'maintenance_checked',
                checker="System",
                status=is_maintenance
            )
            
            return is_maintenance
        except:
            return False

    async def ensure_not_maintenance(self) -> Response:
        """Pre-operation check untuk memastikan sistem tidak dalam maintenance"""
        try:
            if await self.is_maintenance_mode():
                return Response(False, error=MESSAGES.INFO['MAINTENANCE'])
            return Response(True)
        except Exception as e:
            self.logger.error(f"Error checking maintenance mode: {e}")
            await self.callback_manager.trigger('error', 'ensure_not_maintenance', str(e))
            return Response(False, error=str(e))