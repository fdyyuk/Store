"""
Constants for Store DC Bot
Author: fdyyuk
Created at: 2025-03-07 06:30:34 UTC
"""

import discord
from enum import Enum, auto
from typing import Dict, Union

# Currency Settings
class CURRENCY_RATES:
    # Base rates (in WL)
    RATES: Dict[str, int] = {
        'WL': 1,        # 1 WL = 1 WL (base)
        'DL': 100,      # 1 DL = 100 WL
        'BGL': 10000    # 1 BGL = 10000 WL
    }
    
    # Default currency
    DEFAULT = 'WL'
    
    # Supported currencies
    SUPPORTED = ['WL', 'DL', 'BGL']
    
    # Minimum amounts for each currency
    MIN_AMOUNTS = {
        'WL': 1,
        'DL': 1,
        'BGL': 1
    }
    
    # Maximum amounts for each currency
    MAX_AMOUNTS = {
        'WL': 10000,
        'DL': 100,
        'BGL': 10
    }
    
    # Display formats
    FORMATS = {
        'WL': '{} WL',
        'DL': '{} DL',
        'BGL': '{} BGL'
    }
    
    @classmethod
    def to_wl(cls, amount: int, currency: str) -> int:
        """Convert any currency to WL"""
        if currency not in cls.SUPPORTED:
            raise ValueError(f"Unsupported currency: {currency}")
        return amount * cls.RATES[currency]
    
    @classmethod
    def from_wl(cls, wl_amount: int, to_currency: str) -> int:
        """Convert WL to any currency"""
        if to_currency not in cls.SUPPORTED:
            raise ValueError(f"Unsupported currency: {to_currency}")
        return wl_amount // cls.RATES[to_currency]
    
    @classmethod
    def convert(cls, amount: int, from_currency: str, to_currency: str) -> int:
        """Convert between currencies"""
        wl_amount = cls.to_wl(amount, from_currency)
        return cls.from_wl(wl_amount, to_currency)
    
    @classmethod
    def format(cls, amount: int, currency: str) -> str:
        """Format amount in specified currency"""
        if currency not in cls.FORMATS:
            raise ValueError(f"Unsupported currency: {currency}")
        return cls.FORMATS[currency].format(amount)

# Status Enums
class Status(Enum):
    SUCCESS = auto()
    FAILED = auto()
    PENDING = auto()
    CANCELLED = auto()
    ERROR = auto()

# Custom Exceptions
class TransactionError(Exception):
    """Base exception for transaction related errors"""
    pass

class InsufficientBalanceError(TransactionError):
    """Raised when user has insufficient balance"""
    pass

class OutOfStockError(TransactionError):
    """Raised when item is out of stock"""
    pass

# Discord Colors
class COLORS:
    SUCCESS = discord.Color.green()
    ERROR = discord.Color.red()
    WARNING = discord.Color.yellow()
    INFO = discord.Color.blue()
    DEFAULT = discord.Color.blurple()

# Message Templates
class MESSAGES:
    SUCCESS = {
        'PURCHASE': "✅ Pembelian berhasil!\nDetail pembelian:",
        'STOCK_UPDATE': "✅ Stock berhasil diupdate!",
        'DONATION': "✅ Donasi berhasil diterima!",
        'BALANCE_UPDATE': "✅ Balance berhasil diupdate!"
    }
    
    ERROR = {
        'INSUFFICIENT_BALANCE': "❌ Balance tidak cukup!",
        'OUT_OF_STOCK': "❌ Stock habis!",
        'INVALID_AMOUNT': "❌ Jumlah tidak valid!",
        'PERMISSION_DENIED': "❌ Anda tidak memiliki izin!",
        'INVALID_INPUT': "❌ Input tidak valid!",
        'TRANSACTION_FAILED': "❌ Transaksi gagal!"
    }
    
    INFO = {
        'PROCESSING': "⏳ Sedang memproses...",
        'MAINTENANCE': "🛠️ Sistem dalam maintenance",
        'COOLDOWN': "⏳ Mohon tunggu {time} detik"
    }

# Transaction Types
class TransactionType(Enum):
    PURCHASE = "purchase"
    DONATION = "donation"
    ADMIN_ADD = "admin_add"
    ADMIN_REMOVE = "admin_remove"

# Balance Settings
class Balance:
    MIN_AMOUNT = 0
    MAX_AMOUNT = 1000000  # 1M WLS
    DEFAULT_AMOUNT = 0
    DONATION_MIN = 10     # 10 WLS minimum donation

# Update Intervals (in seconds)
class UPDATE_INTERVAL:
    LIVE_STOCK = 60.0    # Update live stock every 60 seconds
    BUTTONS = 30.0       # Update buttons every 30 seconds
    CACHE = 300.0        # Cache timeout 5 minutes
    STATUS = 15.0        # Status update every 15 seconds

# Extensions Configuration
class EXTENSIONS:
    CORE = [
        'ext.balance_manager',
        'ext.product_manager',
        'ext.trx'
    ]
    
    FEATURES = [
        'ext.live_stock',
        'ext.live_buttons',
        'ext.donate'
    ]
    
    OPTIONAL = [
        'cogs.admin',
        'cogs.stats',
        'cogs.automod',
        'cogs.tickets',
        'cogs.welcome',
        'cogs.leveling'
    ]

# Paths Configuration
class PATHS:
    CONFIG = "config.json"
    LOGS = "logs/"
    DATABASE = "database.db"
    BACKUP = "backups/"

# Logging Configuration
class LOGGING:
    FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
    MAX_BYTES = 5 * 1024 * 1024  # 5MB
    BACKUP_COUNT = 5

# Cache Settings
class CACHE_TIMEOUT:
    SHORT = 300    # 5 minutes
    MEDIUM = 3600  # 1 hour
    LONG = 86400   # 24 hours
    PERMANENT = None

# Interaction Settings
class INTERACTION_TIMEOUT:
    SHORT = 60    # 1 minute
    MEDIUM = 180  # 3 minutes
    LONG = 300    # 5 minutes
    BUTTON = 180  # 3 minutes for buttons
    MODAL = 600   # 10 minutes for modals

# Button Custom IDs
class BUTTON_IDS:
    CONFIRM = "confirm_{}"
    CANCEL = "cancel_{}"
    BUY = "buy_{}"
    DONATE = "donate"
    REFRESH = "refresh"

# Product Settings
class Product:
    MAX_STOCK = 999999
    MIN_STOCK = 0
    MAX_PRICE = 1000000  # 1M WLS
    MIN_PRICE = 1        # 1 WL

# Database Settings
class Database:
    TIMEOUT = 5
    MAX_CONNECTIONS = 5
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1

# Stock Settings
class Stock:
    MAX_ITEMS = 1000
    MIN_ITEMS = 0
    UPDATE_BATCH_SIZE = 50
    ALERT_THRESHOLD = 10
    
    class Status(Enum):
        IN_STOCK = "In Stock"
        LOW_STOCK = "Low Stock"
        OUT_OF_STOCK = "Out of Stock"
        DISCONTINUED = "Discontinued"

# API Rate Limits
class RateLimit:
    MAX_REQUESTS = 5
    TIME_WINDOW = 60
    COOLDOWN = 30

# Command Cooldowns (in seconds)
class CommandCooldown:
    DEFAULT = 3
    PURCHASE = 5
    ADMIN = 2
    DONATE = 10

# Discord Message Limits
class MessageLimits:
    EMBED_TITLE = 256
    EMBED_DESCRIPTION = 4096
    EMBED_FIELDS = 25
    EMBED_FIELD_NAME = 256
    EMBED_FIELD_VALUE = 1024
    EMBED_FOOTER = 2048
    EMBED_AUTHOR = 256
    MESSAGE_CONTENT = 2000