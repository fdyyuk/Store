#!/usr/bin/env python3
"""
Discord Bot for Store DC
Author: fdyyuk
Created at: 2025-03-07 18:30:16 UTC
Last Modified: 2025-03-08 06:14:14 UTC
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

# Core imports
import discord
from discord.ext import commands
import json
import logging
import asyncio
import aiohttp
import sqlite3
from datetime import datetime
from logging.handlers import RotatingFileHandler
# [previous imports remain the same until constants import]

# Import constants first
from ext.constants import (
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
    EXTENSIONS,
    LOGGING,
    PATHS,
    Database,
    CommandCooldown
)

# Import database
from database import setup_database, get_connection

# Import handlers and managers
from ext.cache_manager import CacheManager
from ext.base_handler import BaseLockHandler, BaseResponseHandler
from utils.command_handler import AdvancedCommandHandler

# [rest of the code remains the same]
# Initialize basic logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def setup_project_structure():
    """Create necessary directories and files"""
    dirs = ['logs', 'ext', 'utils', 'cogs', 'data', 'temp', 'backups']
    for directory in dirs:
        Path(directory).mkdir(exist_ok=True)
        init_file = Path(directory) / '__init__.py'
        init_file.touch(exist_ok=True)

def check_dependencies():
    """Check if all required dependencies are installed"""
    required = {
        'discord.py': 'discord',
        'aiohttp': 'aiohttp',
        'sqlite3': 'sqlite3',
        'asyncio': 'asyncio'
    }
    
    missing = []
    for package, import_name in required.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package)
    
    if missing:
        logger.critical(f"Missing required packages: {', '.join(missing)}")
        logger.info("Please install required packages using:")
        logger.info(f"pip install {' '.join(missing)}")
        sys.exit(1)

# Check dependencies and setup structure first
check_dependencies()
setup_project_structure()

# Import constants first
from ext.constants import (
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
    EXTENSIONS,
    LOGGING,
    PATHS,
    Database,
    CommandCooldown
)

# Then import other modules
try:
    from database import setup_database, get_connection
    from ext.base_handler import BaseLockHandler, BaseResponseHandler
    from ext.cache_manager import CacheManager
    from utils.command_handler import AdvancedCommandHandler
except ImportError as e:
    logger.critical(f"Failed to import required modules: {e}")
    logger.critical("Please ensure all required files are present and properly structured")
    sys.exit(1)

# Setup enhanced logging
log_dir = Path(PATHS.LOGS)
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=LOGGING.FORMAT,
    handlers=[
        RotatingFileHandler(
            log_dir / 'bot.log',
            maxBytes=LOGGING.MAX_BYTES,
            backupCount=LOGGING.BACKUP_COUNT,
            encoding='utf-8'
        ),
        logging.StreamHandler()
    ]
)

def load_config():
    """Load and validate configuration"""
    required_keys = [
        'token', 
        'guild_id', 
        'admin_id', 
        'id_live_stock',
        'id_log_purch',
        'id_donation_log', 
        'id_history_buy'
    ]
    
    try:
        with open(PATHS.CONFIG, 'r') as f:
            config = json.load(f)
            
        # Validate required keys
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            raise KeyError(f"Missing required config keys: {', '.join(missing_keys)}")
        
        # Validate value types
        int_keys = ['guild_id', 'admin_id', 'id_live_stock', 'id_log_purch', 
                   'id_donation_log', 'id_history_buy']
        
        for key in int_keys:
            try:
                config[key] = int(config[key])
            except (ValueError, TypeError):
                raise ValueError(f"Invalid value for {key}. Expected integer.")
                
        # Set default values if not present
        defaults = {
            'cooldown_time': CommandCooldown.DEFAULT,
            'max_items': Stock.MAX_ITEMS,
            'cache_timeout': CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.SHORT)
        }
        
        for key, value in defaults.items():
            if key not in config:
                config[key] = value
        
        return config
    except FileNotFoundError:
        logger.critical(f"Config file not found: {PATHS.CONFIG}")
        logger.info("Please create a config.json file with required settings")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.critical(f"Invalid JSON in config file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Error loading config: {e}")
        sys.exit(1)

class StoreBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        
        self.config = load_config()
        self.cache_manager = CacheManager()
        self.start_time = datetime.utcnow()
        self.maintenance_mode = False
        self._ready = asyncio.Event()
        
    async def wait_until_ready(self) -> None:
        """Override to ensure bot is fully ready"""
        await super().wait_until_ready()
        await self._ready.wait()
        
    async def setup_hook(self):
        """Setup bot extensions and database"""
        try:
            # Setup database first
            setup_database()
            
            # Load core extensions first
            for ext in EXTENSIONS.CORE:
                try:
                    await self.load_extension(ext)
                    logger.info(f"Loaded core extension: {ext}")
                except Exception as e:
                    logger.error(f"Failed to load core extension {ext}: {e}")
                    await self.close()
                    return
            
            # Load feature extensions
            for ext in EXTENSIONS.FEATURES:
                try:
                    await self.load_extension(ext)
                    logger.info(f"Loaded feature extension: {ext}")
                except Exception as e:
                    logger.error(f"Failed to load feature extension {ext}: {e}")
            
            # Load optional extensions
            for ext in EXTENSIONS.OPTIONAL:
                try:
                    await self.load_extension(ext)
                    logger.info(f"Loaded optional extension: {ext}")
                except Exception as e:
                    logger.warning(f"Failed to load optional extension {ext}: {e}")
            
            logger.info("Bot setup completed")
        except Exception as e:
            logger.critical(f"Failed to setup bot: {e}")
            await self.close()
    
    async def on_ready(self):
        """Called when bot is ready"""
        if self._ready.is_set():
            return
            
        logger.info(f"Logged in as {self.user.name} ({self.user.id})")
        logger.info(f"Discord.py Version: {discord.__version__}")
        
        # Set bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="Growtopia Shop 🏪"
        )
        await self.change_presence(activity=activity)
        
        # Clear expired cache
        await self.cache_manager.clear_expired()
        
        # Signal bot is fully ready
        self._ready.set()
        
    async def on_error(self, event_method: str, *args, **kwargs):
        """Global error handler"""
        exc_type, exc_value, exc_traceback = sys.exc_info()
        logger.error(f"Error in {event_method}: {exc_type.__name__}: {exc_value}")
        
    async def close(self):
        """Cleanup before closing"""
        try:
            # Cleanup tasks
            if hasattr(self, 'cache_manager'):
                await self.cache_manager.clear_all()
            
            # Cancel all tasks
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            [task.cancel() for task in tasks]
            
            await asyncio.gather(*tasks, return_exceptions=True)
            await super().close()
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            logger.info("Bot shutdown complete")

async def run_bot():
    """Run the bot"""
    bot = StoreBot()
    
    try:
        async with bot:
            await bot.start(bot.config['token'])
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except discord.LoginFailure:
        logger.critical("Invalid bot token")
    except Exception as e:
        logger.critical(f"Bot crashed: {e}")
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)