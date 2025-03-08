"""
Enhanced Cache Manager with Database Integration
Author: fdyyuk
Created at: 2025-03-07 18:04:56 UTC
Last Modified: 2025-03-08 05:42:06 UTC
"""

import logging
import time
import json
from typing import Optional, Any, Dict
from datetime import datetime, timedelta
from sqlite3 import Connection, Error as SQLiteError
from database import get_connection
import asyncio
from functools import wraps
from .constants import CACHE_TIMEOUT, Balance

logger = logging.getLogger(__name__)

class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON Encoder untuk menangani object khusus"""
    def default(self, obj):
        if isinstance(obj, Balance):
            return {
                '__class__': 'Balance',
                'wl': obj.wl,
                'dl': obj.dl,
                'bgl': obj.bgl
            }
        if isinstance(obj, datetime):
            return {'__datetime__': obj.isoformat()}
        if isinstance(obj, timedelta):
            return {'__timedelta__': obj.total_seconds()}
        return super().default(obj)

class CustomJSONDecoder(json.JSONDecoder):
    """Custom JSON Decoder untuk mengembalikan object khusus"""
    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj):
        if '__class__' in obj:
            if obj['__class__'] == 'Balance':
                return Balance(obj['wl'], obj['dl'], obj['bgl'])
        if '__datetime__' in obj:
            return datetime.fromisoformat(obj['__datetime__'])
        if '__timedelta__' in obj:
            return timedelta(seconds=obj['__timedelta__'])
        return obj

class CacheManager:
    """Enhanced Cache Manager dengan Database Integration"""
    _instance = None
    _lock = asyncio.Lock()
    MAX_MEMORY_ITEMS = 10000  # Batasan item di memory
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.memory_cache: Dict[str, Dict] = {}
            self.logger = logging.getLogger('CacheManager')
            self.initialized = True
    
    async def _enforce_memory_limit(self):
        """Enforce memory cache size limit"""
        if len(self.memory_cache) > self.MAX_MEMORY_ITEMS:
            # Hapus 10% item terlama
            items_to_remove = sorted(
                self.memory_cache.items(),
                key=lambda x: x[1]['expires_at']
            )[:int(self.MAX_MEMORY_ITEMS * 0.1)]
            for key, _ in items_to_remove:
                del self.memory_cache[key]
    
    async def get(self, key: str, default: Any = None) -> Optional[Any]:
        """Ambil data dari cache (memory atau database)"""
        try:
            # Cek memory cache dulu
            if key in self.memory_cache:
                cache_data = self.memory_cache[key]
                if self._is_valid(cache_data):
                    self.logger.debug(f"Cache hit (memory): {key}")
                    return cache_data['value']
                else:
                    # Hapus cache yang expired
                    del self.memory_cache[key]
            
            # Jika tidak ada di memory, cek database
            async with self._lock:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT value, expires_at FROM cache_table WHERE key = ?",
                        (key,)
                    )
                    result = cursor.fetchone()
                    
                    if result:
                        value, expires_at = result
                        expires_at = datetime.fromisoformat(expires_at)
                        
                        if expires_at > datetime.utcnow():
                            # Cache masih valid
                            try:
                                decoded_value = json.loads(
                                    value,
                                    cls=CustomJSONDecoder
                                )
                                # Simpan ke memory cache
                                self.memory_cache[key] = {
                                    'value': decoded_value,
                                    'expires_at': expires_at
                                }
                                await self._enforce_memory_limit()
                                self.logger.debug(f"Cache hit (database): {key}")
                                return decoded_value
                            except json.JSONDecodeError:
                                self.logger.warning(f"Failed to decode cache value for key: {key}")
                                return value
                        else:
                            # Hapus cache yang expired
                            cursor.execute("DELETE FROM cache_table WHERE key = ?", (key,))
                            conn.commit()
                    
                    return default
                    
                except SQLiteError as e:
                    self.logger.error(f"Database error in get: {e}")
                    return default
                finally:
                    conn.close()
        
        except Exception as e:
            self.logger.error(f"Error in get: {e}")
            return default
    
    async def set(self, 
                  key: str, 
                  value: Any, 
                  expires_in: Optional[int] = None,
                  permanent: bool = False) -> bool:
        """
        Simpan data ke cache
        
        Args:
            key: Kunci cache
            value: Nilai yang akan disimpan
            expires_in: Waktu kadaluarsa dalam detik (None untuk permanent)
            permanent: Jika True, simpan ke database
        """
        try:
            # Handle permanent cache
            if expires_in is None:
                expires_in = CACHE_TIMEOUT.get_seconds(CACHE_TIMEOUT.PERMANENT)
                
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            # Simpan ke memory cache
            self.memory_cache[key] = {
                'value': value,
                'expires_at': expires_at
            }
            await self._enforce_memory_limit()
            
            # Jika permanent, simpan juga ke database
            if permanent:
                async with self._lock:
                    conn = get_connection()
                    try:
                        cursor = conn.cursor()
                        
                        # Konversi value ke JSON dengan custom encoder
                        json_value = json.dumps(value, cls=CustomJSONEncoder)
                            
                        cursor.execute("""
                            INSERT OR REPLACE INTO cache_table (key, value, expires_at)
                            VALUES (?, ?, ?)
                        """, (key, json_value, expires_at.isoformat()))
                        
                        conn.commit()
                        self.logger.debug(f"Cache set (permanent): {key}")
                        return True
                        
                    except SQLiteError as e:
                        self.logger.error(f"Database error in set: {e}")
                        return False
                    finally:
                        conn.close()
            
            self.logger.debug(f"Cache set (memory): {key}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in set: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Hapus item dari cache"""
        try:
            # Hapus dari memory cache
            if key in self.memory_cache:
                del self.memory_cache[key]
            
            # Hapus dari database
            async with self._lock:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM cache_table WHERE key = ?", (key,))
                    conn.commit()
                    return True
                except SQLiteError as e:
                    self.logger.error(f"Database error in delete: {e}")
                    return False
                finally:
                    conn.close()
                    
        except Exception as e:
            self.logger.error(f"Error in delete: {e}")
            return False
    
    async def clear(self) -> bool:
        """Bersihkan semua cache"""
        try:
            # Bersihkan memory cache
            self.memory_cache.clear()
            
            # Bersihkan database cache
            async with self._lock:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM cache_table")
                    conn.commit()
                    return True
                except SQLiteError as e:
                    self.logger.error(f"Database error in clear: {e}")
                    return False
                finally:
                    conn.close()
                    
        except Exception as e:
            self.logger.error(f"Error in clear: {e}")
            return False
    
    async def cleanup(self) -> None:
        """Bersihkan cache yang expired"""
        try:
            # Bersihkan memory cache
            current_time = datetime.utcnow()
            expired_keys = [
                key for key, data in self.memory_cache.items()
                if data['expires_at'] <= current_time
            ]
            for key in expired_keys:
                del self.memory_cache[key]
            
            # Bersihkan database cache
            async with self._lock:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM cache_table WHERE expires_at < ?",
                        (current_time.isoformat(),)
                    )
                    conn.commit()
                except SQLiteError as e:
                    self.logger.error(f"Database error in cleanup: {e}")
                finally:
                    conn.close()
                    
        except Exception as e:
            self.logger.error(f"Error in cleanup: {e}")
    
    def _is_valid(self, cache_data: Dict) -> bool:
        """Cek apakah cache masih valid"""
        return cache_data['expires_at'] > datetime.utcnow()

    async def get_stats(self) -> Dict:
        """Dapatkan statistik cache"""
        try:
            memory_cache_size = len(self.memory_cache)
            memory_cache_valid = sum(
                1 for data in self.memory_cache.values()
                if self._is_valid(data)
            )
            
            async with self._lock:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM cache_table")
                    db_cache_size = cursor.fetchone()[0]
                    
                    cursor.execute(
                        "SELECT COUNT(*) FROM cache_table WHERE expires_at > ?",
                        (datetime.utcnow().isoformat(),)
                    )
                    db_cache_valid = cursor.fetchone()[0]
                    
                    return {
                        'memory_cache': {
                            'total': memory_cache_size,
                            'valid': memory_cache_valid,
                            'expired': memory_cache_size - memory_cache_valid
                        },
                        'db_cache': {
                            'total': db_cache_size,
                            'valid': db_cache_valid,
                            'expired': db_cache_size - db_cache_valid
                        }
                    }
                finally:
                    conn.close()
                    
        except Exception as e:
            self.logger.error(f"Error getting cache stats: {e}")
            return {}

# Decorator untuk caching
def cached(expires_in: Optional[int] = None, permanent: bool = False):
    """
    Decorator untuk caching fungsi
    
    Args:
        expires_in: Waktu kadaluarsa dalam detik (None untuk menggunakan PERMANENT)
        permanent: Jika True, simpan ke database
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{hash(str(args))}-{hash(str(kwargs))}"
            cache_manager = CacheManager()
            
            # Coba ambil dari cache
            cached_value = await cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Jika tidak ada di cache, eksekusi fungsi
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            
            # Simpan ke cache
            await cache_manager.set(cache_key, result, expires_in, permanent)
            
            return result
        return wrapper
    return decorator