#!/usr/bin/env python3
"""
Discord Bot for Store DC
Author: fdyyuk
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

# Initialize basic logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def check_dependencies():
    """Check if all required dependencies are installed"""
    required = {
        'discord.py': 'discord',
        'aiohttp': 'aiohttp',
        'sqlite3': 'sqlite3'
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

def setup_project_structure():
    """Create necessary directories and files"""
    dirs = ['logs', 'ext', 'utils', 'cogs']
    for directory in dirs:
        Path(directory).mkdir(exist_ok=True)
        init_file = Path(directory) / '__init__.py'
        init_file.touch(exist_ok=True)

# Check dependencies before proceeding
check_dependencies()

# Create project structure
setup_project_structure()

# Now try importing local modules
try:
    from database import setup_database, get_connection
    from utils.command_handler import AdvancedCommandHandler
    from ext.base_handler import BaseLockHandler, BaseResponseHandler
    from ext.cache_manager import CacheManager
    from ext.constants import (
        COLORS,
        MESSAGES,
        EXTENSIONS,
        LOGGING,
        PATHS
    )
except ImportError as e:
    logger.critical(f"Failed to import required modules: {e}")
    logger.critical("Please ensure all required files are present and properly structured")
    sys.exit(1)

# Setup enhanced logging
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=LOGGING.FORMAT,
    handlers=[
        logging.FileHandler(log_dir / 'bot.log'),
        logging.StreamHandler()
    ]
)

def load_config():
    """Load and validate configuration"""
    required_keys = [
        'token', 'guild_id', 'admin_id', 
        'id_live_stock', 'id_log_purch',
        'id_donation_log', 'id_history_buy'
    ]
    
    try:
        with open(PATHS.CONFIG, 'r') as f:
            config = json.load(f)
            
        # Validate required keys
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            raise KeyError(f"Missing required config keys: {', '.join(missing_keys)}")
            
        return config
    except FileNotFoundError:
        logger.critical(f"Config file not found: {PATHS.CONFIG}")
        logger.info("Please create a config.json file with required settings")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.critical(f"Invalid JSON in config file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Failed to load config: {e}")
        raise

class MyBot(commands.Bot, BaseLockHandler, BaseResponseHandler):
    """Main bot class"""
    
    def __init__(self):
        # Setup intents
        intents = discord.Intents.all()
        super().__init__(command_prefix='!', intents=intents)
        BaseLockHandler.__init__(self)
        
        # Load configuration
        self.config = config
        self.session = None
        
        # Initialize IDs
        try:
            self.admin_id = int(config['admin_id'])
            self.guild_id = int(config['guild_id'])
            self.live_stock_channel_id = int(config['id_live_stock'])
            self.log_purchase_channel_id = int(config['id_log_purch'])
            self.donation_log_channel_id = int(config['id_donation_log'])
            self.history_buy_channel_id = int(config['id_history_buy'])
        except ValueError as e:
            logger.critical(f"Invalid ID in config: {e}")
            raise
        
        # Initialize components
        self.startup_time = datetime.utcnow()
        self.command_handler = AdvancedCommandHandler(self)
        self.cache_manager = CacheManager()

    async def setup_hook(self):
        """Initialize bot components"""
        self.session = aiohttp.ClientSession()
        
        # Load extensions
        for ext_type, extensions in {
            'Core': EXTENSIONS.CORE,
            'Features': EXTENSIONS.FEATURES,
            'Optional': EXTENSIONS.OPTIONAL
        }.items():
            logger.info(f"\nLoading {ext_type} extensions:")
            for extension in extensions:
                try:
                    await self.load_extension(extension)
                    logger.info(f"✓ {extension}")
                except Exception as e:
                    logger.error(f"✗ {extension}: {e}")

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f"\nLogged in as: {self.user.name} (ID: {self.user.id})")
        logger.info(f"Guild ID: {self.guild_id}")
        
        # Set presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Growtopia Shop | !help"
            ),
            status=discord.Status.online
        )
        logger.info("Bot is ready!")

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Simple ping command to test bot responsiveness"""
        await ctx.send(f"Pong! Latency: {round(self.latency * 1000)}ms")

    async def close(self):
        """Cleanup when bot shuts down"""
        if self.session:
            await self.session.close()
        await super().close()

async def main():
    """Main entry point"""
    try:
        # Initialize database
        setup_database()
        
        # Create and start bot
        bot = MyBot()
        async with bot:
            await bot.start(TOKEN)
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    # Load config first
    try:
        config = load_config()
        TOKEN = config['token']
    except Exception as e:
        logger.critical(f"Failed to initialize: {e}")
        sys.exit(1)

    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nBot stopped by user")
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
        logger.exception("Error details:")
        sys.exit(1)