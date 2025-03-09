"""
Constants for Store DC Bot
Author: fdyyuk
Created at: 2025-03-07 18:04:56 UTC
Last Modified: 2025-03-08 14:28:37 UTC
"""

import discord
from enum import Enum, auto
from typing import Dict, Union, List
from datetime import timedelta

# Tambahkan di bagian atas file setelah import
COG_LOADED = {
    'PRODUCT': 'product_manager_loaded',
    'BALANCE': 'balance_manager_loaded',
    'TRANSACTION': 'transaction_manager_loaded',
    'LIVE_STOCK': 'live_stock_loaded', 
    'LIVE_BUTTONS': 'live_buttons_loaded',
    'ADMIN': 'admin_service_loaded'
}
# File Size Settings
MAX_STOCK_FILE_SIZE = 5 * 1024 * 1024  # 5MB max file size for stock files
MAX_ATTACHMENT_SIZE = 8 * 1024 * 1024  # 8MB max attachment size
MAX_EMBED_SIZE = 6000  # Discord embed character limit

# Valid Stock Formats
VALID_STOCK_FORMATS = ['txt']  # Format file yang diizinkan untuk stock

# Transaction Types
class TransactionType(Enum):
    PURCHASE = "purchase"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DONATION = "donation"
    ADMIN_ADD = "admin_add"
    ADMIN_REMOVE = "admin_remove"
    ADMIN_RESET = "admin_reset"
    REFUND = "refund"
    TRANSFER = "transfer"

# Status untuk database
class Status(Enum):
    AVAILABLE = "available"  # Status di database
    SOLD = "sold"          # Status di database
    DELETED = "deleted"    # Status di database

# Balance Class yang lengkap
class Balance:
    def __init__(self, wl: int = 0, dl: int = 0, bgl: int = 0):
        self.wl = max(0, wl)
        self.dl = max(0, dl)
        self.bgl = max(0, bgl)
        self.MIN_AMOUNT = 0
        self.MAX_AMOUNT = 1000000  # 1M WLS
        self.DEFAULT_AMOUNT = 0
        self.DONATION_MIN = 10     # 10 WLS minimum donation

    def total_wl(self) -> int:
        """Convert semua balance ke WL"""
        return self.wl + (self.dl * 100) + (self.bgl * 10000)

    def format(self) -> str:
        """Format balance untuk display"""
        parts = []
        if self.bgl > 0:
            parts.append(f"{self.bgl:,} BGL")
        if self.dl > 0:
            parts.append(f"{self.dl:,} DL")
        if self.wl > 0 or not parts:
            parts.append(f"{self.wl:,} WL")
        return ", ".join(parts)

    @classmethod
    def from_wl(cls, total_wl: int) -> 'Balance':
        """Buat Balance object dari total WL"""
        bgl = total_wl // 10000
        remaining = total_wl % 10000
        dl = remaining // 100
        wl = remaining % 100
        return cls(wl, dl, bgl)

    def __eq__(self, other):
        if not isinstance(other, Balance):
            return False
        return self.total_wl() == other.total_wl()

    def __str__(self):
        return self.format()

    def validate(self) -> bool:
        """Validasi balance"""
        total = self.total_wl()
        return self.MIN_AMOUNT <= total <= self.MAX_AMOUNT

class EXTENSIONS:
    # Core services harus diload pertama dan berurutan
    SERVICES: List[str] = [
        'ext.product_manager',    # Load 1st - independent
        'ext.balance_manager',    # Load 2nd - depends on product_manager
        'ext.trx'                # Load 3rd - depends on both above
    ]
    
    # Core features yang bergantung pada services
    FEATURES: List[str] = [
        'ext.admin_service',
        'ext.live_stock',        # Depends on product_manager
        'ext.live_buttons',      # Depends on services
        'ext.donate'             # Depends on balance_manager
    ]
    
    # Cogs yang menggunakan services - load terakhir
    COGS: List[str] = [
        'cogs.stats',
        'cogs.automod',
        'cogs.tickets',
        'cogs.welcome', 
        'cogs.leveling',
        'cogs.admin'            # Admin paling terakhir karena bergantung pada semua service
    ]
    
    # Urutan loading yang benar
    ALL: List[str] = SERVICES + FEATURES + COGS
    
    @classmethod
    def verify_loaded(cls, bot) -> bool:
        """Verifikasi semua service sudah terload dengan benar"""
        required_services = [
            'ProductManagerCog',
            'BalanceManagerCog', 
            'TransactionCog'
        ]
        return all(bot.get_cog(service) for service in required_services)

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
        'WL': '{:,} WL',
        'DL': '{:,} DL',
        'BGL': '{:,} BGL'
    }
    
    @classmethod
    def to_wl(cls, amount: Union[int, float], currency: str) -> float:
        """Convert any currency to WL"""
        if currency not in cls.SUPPORTED:
            raise ValueError(f"Mata uang tidak didukung: {currency}")
        return float(amount) * cls.RATES[currency]
    
    @classmethod
    def from_wl(cls, wl_amount: Union[int, float], to_currency: str) -> float:
        """Convert WL to any currency"""
        if to_currency not in cls.SUPPORTED:
            raise ValueError(f"Mata uang tidak didukung: {to_currency}")
        return float(wl_amount) / cls.RATES[to_currency]
    
    @classmethod
    def convert(cls, amount: Union[int, float], from_currency: str, to_currency: str) -> float:
        """Convert between currencies"""
        wl_amount = cls.to_wl(amount, from_currency)
        return cls.from_wl(wl_amount, to_currency)
    
    @classmethod
    def format(cls, amount: Union[int, float], currency: str) -> str:
        """Format amount in specified currency"""
        if currency not in cls.FORMATS:
            raise ValueError(f"Mata uang tidak didukung: {currency}")
        return cls.FORMATS[currency].format(amount)

# Stock Settings
class Stock:
    MAX_ITEMS = 1000
    MIN_ITEMS = 0
    UPDATE_BATCH_SIZE = 50
    ALERT_THRESHOLD = 10
    MAX_STOCK = 999999
    MIN_STOCK = 0

# Discord Colors - Updated with new colors
class COLORS:
    SUCCESS = discord.Color.green()
    ERROR = discord.Color.red()
    WARNING = discord.Color.yellow()
    INFO = discord.Color.blue()
    DEFAULT = discord.Color.blurple()
    SHOP = discord.Color.purple()      # New
    ADMIN = discord.Color.dark_grey()  # New
    PRODUCT = discord.Color.teal()     # New

# Message Templates - Updated with new messages
class MESSAGES:
    SUCCESS = {
        'PURCHASE': "✅ Pembelian berhasil!\nDetail pembelian:",
        'STOCK_UPDATE': "✅ Stock berhasil diupdate!",
        'DONATION': "✅ Donasi berhasil diterima!",
        'BALANCE_UPDATE': "✅ Balance berhasil diupdate!",
        'REGISTRATION': "✅ Registrasi berhasil! GrowID: {growid}",
        'WORLD_UPDATE': "✅ World info berhasil diupdate!",
        'PRODUCT_CREATED': "✅ Product created successfully.",      # New
        'PRODUCT_UPDATED': "✅ Product updated successfully.",      # New
        'PRODUCT_DELETED': "✅ Product deleted successfully.",      # New
        'STOCK_SOLD': "✅ Stock sold successfully.",               # New
        'CACHE_CLEARED': "✅ Cache cleared successfully.",          # New  <-- Tambahkan koma di sini
        'COG_LOADED': "✅ {} loaded successfully."                  # New
    }
    ERROR = {
        'INSUFFICIENT_BALANCE': "❌ Balance tidak cukup!",
        'OUT_OF_STOCK': "❌ Stock habis!",
        'INVALID_AMOUNT': "❌ Jumlah tidak valid!",
        'PERMISSION_DENIED': "❌ Anda tidak memiliki izin!",
        'INVALID_INPUT': "❌ Input tidak valid!",
        'TRANSACTION_FAILED': "❌ Transaksi gagal!",
        'REGISTRATION_FAILED': "❌ Registrasi gagal! Silakan coba lagi.",
        'NOT_REGISTERED': "❌ Anda belum terdaftar! Gunakan tombol Register.",
        'BALANCE_NOT_FOUND': "❌ Balance tidak ditemukan!",
        'BALANCE_FAILED': "❌ Gagal mengambil informasi balance!",
        'WORLD_INFO_FAILED': "❌ Gagal mengambil informasi world!",
        'NO_HISTORY': "❌ Tidak ada riwayat transaksi!",
        'INVALID_GROWID': "❌ GrowID tidak valid!",
        'PRODUCT_NOT_FOUND': "❌ Produk tidak ditemukan!",
        'INSUFFICIENT_STOCK': "❌ Stock tidak mencukupi!",
        'INVALID_PRODUCT_CODE': "❌ Invalid product code format.",        # New
        'PRODUCT_EXISTS': "❌ Product with this code already exists.",    # New
        'CACHE_ERROR': "❌ Error accessing cache. Please try again.",     # New
        'DATABASE_ERROR': "❌ Database error occurred. Please try again.", # New
        'LOCK_ACQUISITION_FAILED': "❌ Could not acquire lock. Please try again." # New
    }
    
    INFO = {
        'PROCESSING': "⏳ Sedang memproses...",
        'MAINTENANCE': "🛠️ Sistem dalam maintenance",
        'COOLDOWN': "⏳ Mohon tunggu {time} detik"
    }

# Product Manager Constants (New)
class PRODUCT_CONSTANTS:
    """Konstanta khusus untuk product manager"""
    MAX_NAME_LENGTH = 50
    MAX_CODE_LENGTH = 20
    MAX_DESCRIPTION_LENGTH = 200
    MIN_PRICE = 1
    CACHE_PREFIX = "product_"
    DEFAULT_SORT = "code"
    VALID_SORT_FIELDS = ["code", "name", "price"]

# Event Types for Callback System (New)
class EVENTS:
    """Event types untuk callback system"""
    PRODUCT = {
        'CREATED': 'product_created',
        'UPDATED': 'product_updated',
        'DELETED': 'product_deleted',
        'VIEWED': 'product_viewed'
    }
    
    STOCK = {
        'ADDED': 'stock_added',
        'UPDATED': 'stock_updated',
        'SOLD': 'stock_sold',
        'LOW': 'stock_low'
    }
    
    WORLD = {
        'UPDATED': 'world_updated',
        'ACCESSED': 'world_accessed'
    }
    
    SYSTEM = {
        'ERROR': 'error',
        'WARNING': 'warning',
        'INFO': 'info',
        'DEBUG': 'debug'
    }

# Permission Levels (New)
class PERMISSIONS:
    """Permission levels untuk product manager"""
    VIEW = 0      # Can view products and stock
    PURCHASE = 1  # Can purchase products
    STOCK = 2     # Can manage stock
    ADMIN = 3     # Can manage products and settings
    OWNER = 4     # Full access

# Button IDs (Existing)
class BUTTON_IDS:
    # Basic Buttons
    CONFIRM = "confirm_{}"
    CANCEL = "cancel_{}"
    BUY = "buy"
    DONATE = "donate"
    REFRESH = "refresh"
    
    # Shop Buttons
    REGISTER = "register"
    BALANCE = "balance"
    WORLD_INFO = "world_info"
    CONFIRM_PURCHASE = "confirm_purchase"
    CANCEL_PURCHASE = "cancel_purchase"
    HISTORY = "history"
    
    @classmethod
    def get_purchase_confirmation_id(cls, product_code: str) -> str:
        """Generate ID untuk konfirmasi pembelian"""
        return f"{cls.CONFIRM_PURCHASE}_{product_code}"
        
    @classmethod
    def get_confirm_id(cls, action_id: str) -> str:
        """Generate ID untuk konfirmasi umum"""
        return cls.CONFIRM.format(action_id)
        
    @classmethod
    def get_cancel_id(cls, action_id: str) -> str:
        """Generate ID untuk pembatalan umum"""
        return cls.CANCEL.format(action_id)

# Update Intervals (Existing)
class UPDATE_INTERVAL:
    LIVE_STOCK = 55.0    # Update live stock every 55 seconds
    BUTTONS = 30.0       # Update buttons every 30 seconds
    CACHE = 300.0        # Cache timeout 5 minutes
    STATUS = 15.0        # Status update every 15 seconds

# Cache Settings (Existing)
class CACHE_TIMEOUT:
    SHORT = timedelta(minutes=5)      # 5 menit
    MEDIUM = timedelta(hours=1)       # 1 jam
    LONG = timedelta(days=1)          # 24 jam
    PERMANENT = timedelta(days=3650)  # 10 tahun (effectively permanent)

    @classmethod
    def get_seconds(cls, timeout: timedelta) -> int:
        """Convert timedelta ke detik"""
        return int(timeout.total_seconds())

# Command Cooldowns (Existing)
class CommandCooldown:
    DEFAULT = 3
    PURCHASE = 5
    ADMIN = 2
    DONATE = 10

# Database Settings (Existing)
class Database:
    TIMEOUT = 5
    MAX_CONNECTIONS = 5
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1
    BACKUP_INTERVAL = 86400  # 24 hours

# Paths Configuration (Existing)
class PATHS:
    CONFIG = "config.json"
    LOGS = "logs/"
    DATABASE = "database.db"
    BACKUP = "backups/"
    TEMP = "temp/"

# Logging Configuration (Existing)
class LOGGING:
    FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
    MAX_BYTES = 5 * 1024 * 1024  # 5MB
    BACKUP_COUNT = 5

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

# Product Manager Exceptions (New)
class ProductError(Exception):
    """Base exception for product related errors"""
    pass

class ProductNotFoundError(ProductError):
    """Raised when product is not found"""
    pass

class InvalidProductCodeError(ProductError):
    """Raised when product code is invalid"""
    pass

class StockLimitError(ProductError):
    """Raised when stock limit is reached"""
    pass

class LockError(Exception):
    """Raised when lock acquisition fails"""
    pass

# Notification Channel IDs for Product Manager (New)
class NOTIFICATION_CHANNELS:
    """Channel IDs untuk notifikasi sistem"""
    TRANSACTIONS = 0      # Ganti dengan ID channel transaksi
    PRODUCT_LOGS = 0     # Ganti dengan ID channel product logs
    STOCK_LOGS = 0       # Ganti dengan ID channel stock logs
    ADMIN_LOGS = 0       # Ganti dengan ID channel admin logs
    ERROR_LOGS = 0       # Ganti dengan ID channel error logs
    SHOP = 0            # Ganti dengan ID channel shop