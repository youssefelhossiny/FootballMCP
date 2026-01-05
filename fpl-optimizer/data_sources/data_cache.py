"""
Data Caching Layer
Implements TTL-based caching for external data sources to reduce API calls
"""

import pickle
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


class DataCache:
    """Simple TTL-based cache with pickle and JSON support"""

    def __init__(self, cache_dir: str = "cache", ttl_hours: int = 6):
        """
        Initialize cache

        Args:
            cache_dir: Directory to store cache files
            ttl_hours: Time-to-live in hours (default 6 hours)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
        self.cache = {}

    def _get_cache_path(self, key: str, format: str = "pkl") -> Path:
        """Get path to cache file for a given key"""
        safe_key = key.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe_key}.{format}"

    def get(self, key: str, format: str = "pkl", ignore_expiry: bool = False) -> Optional[Any]:
        """
        Get value from cache if it exists and is not expired

        Args:
            key: Cache key
            format: 'pkl' for pickle or 'json' for JSON
            ignore_expiry: If True, return cached data even if expired (for fallback scenarios)

        Returns:
            Cached value if valid, None if expired or not found
        """
        cache_path = self._get_cache_path(key, format)

        if not cache_path.exists():
            return None

        try:
            # Load based on format
            if format == "json":
                with open(cache_path, 'r') as f:
                    cache_data = json.load(f)
            else:  # pickle
                with open(cache_path, 'rb') as f:
                    cache_data = pickle.load(f)

            # Check expiry
            timestamp = datetime.fromisoformat(cache_data['timestamp'])
            age_hours = (datetime.now() - timestamp).total_seconds() / 3600

            if datetime.now() - timestamp < self.ttl:
                print(f"✅ Cache hit for '{key}' (age: {age_hours:.1f}h)")
                return cache_data['data']
            elif ignore_expiry:
                print(f"⚠️ Using stale cache for '{key}' (age: {age_hours:.1f}h)")
                return cache_data['data']
            else:
                print(f"⏰ Cache expired for '{key}' (age: {age_hours:.1f}h)")
                return None

        except Exception as e:
            print(f"❌ Error reading cache for '{key}': {e}")
            return None

    def set(self, key: str, value: Any, format: str = "pkl"):
        """
        Store value in cache with current timestamp

        Args:
            key: Cache key
            value: Value to cache
            format: 'pkl' for pickle or 'json' for JSON
        """
        cache_path = self._get_cache_path(key, format)

        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'data': value
            }

            # Save based on format
            if format == "json":
                with open(cache_path, 'w') as f:
                    json.dump(cache_data, f, indent=2)
            else:  # pickle
                with open(cache_path, 'wb') as f:
                    pickle.dump(cache_data, f)

            print(f"💾 Cached '{key}' ({format} format)")

        except Exception as e:
            print(f"❌ Error writing cache for '{key}': {e}")

    def invalidate(self, key: str, format: str = "pkl"):
        """
        Remove a specific key from cache

        Args:
            key: Cache key to invalidate
            format: 'pkl' or 'json'
        """
        cache_path = self._get_cache_path(key, format)

        try:
            if cache_path.exists():
                cache_path.unlink()
                print(f"🗑️  Invalidated cache for '{key}'")
            else:
                print(f"ℹ️  No cache found for '{key}'")

        except Exception as e:
            print(f"❌ Error invalidating cache for '{key}': {e}")

    def clear_all(self):
        """Remove all cached files"""
        try:
            count = 0
            for cache_file in self.cache_dir.glob("*"):
                cache_file.unlink()
                count += 1

            print(f"🗑️  Cleared {count} cache files")

        except Exception as e:
            print(f"❌ Error clearing cache: {e}")

    def get_cache_info(self) -> dict:
        """
        Get information about all cached items

        Returns:
            Dict with cache statistics
        """
        cache_files = list(self.cache_dir.glob("*"))

        info = {
            'total_files': len(cache_files),
            'cache_dir': str(self.cache_dir),
            'ttl_hours': self.ttl.total_seconds() / 3600,
            'files': []
        }

        for cache_file in cache_files:
            try:
                # Try to load and check age
                format_type = cache_file.suffix[1:]  # Remove the dot

                if format_type == "json":
                    with open(cache_file, 'r') as f:
                        cache_data = json.load(f)
                else:
                    with open(cache_file, 'rb') as f:
                        cache_data = pickle.load(f)

                timestamp = datetime.fromisoformat(cache_data['timestamp'])
                age_hours = (datetime.now() - timestamp).total_seconds() / 3600
                is_expired = age_hours >= (self.ttl.total_seconds() / 3600)

                info['files'].append({
                    'key': cache_file.stem,
                    'format': format_type,
                    'age_hours': round(age_hours, 2),
                    'expired': is_expired,
                    'size_kb': round(cache_file.stat().st_size / 1024, 2)
                })

            except Exception as e:
                info['files'].append({
                    'key': cache_file.stem,
                    'error': str(e)
                })

        return info


# Testing
if __name__ == "__main__":
    # Create cache with 1 hour TTL for testing
    cache = DataCache(ttl_hours=1)

    # Test data
    test_data = {
        'players': [
            {'name': 'Salah', 'xG': 15.2, 'xA': 8.5},
            {'name': 'Haaland', 'xG': 18.7, 'xA': 4.2}
        ]
    }

    # Set cache
    print("Testing cache operations...")
    cache.set('understat_epl_2024', test_data, format='json')

    # Get cache
    cached_data = cache.get('understat_epl_2024', format='json')
    print(f"Retrieved data: {cached_data}")

    # Get cache info
    info = cache.get_cache_info()
    print(f"\nCache info:")
    print(f"  Total files: {info['total_files']}")
    print(f"  TTL: {info['ttl_hours']} hours")
    for file in info['files']:
        print(f"  - {file['key']}: {file['size_kb']} KB, age {file['age_hours']}h, "
              f"expired: {file.get('expired', 'N/A')}")

    # Clear cache
    cache.clear_all()
