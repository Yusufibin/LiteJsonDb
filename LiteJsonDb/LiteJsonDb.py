"""
██╗░░░░░██╗████████╗███████╗░░░░░██╗░██████╗░█████╗░███╗░░██╗██████╗░██████╗░░░░██████╗░██╗░░░██╗
██║░░░░░██║╚══██╔══╝██╔════╝░░░░░██║██╔════╝██╔══██╗████╗░██║██╔══██╗██╔══██╗░░░██╔══██╗╚██╗░██╔╝
██║░░░░░██║░░░██║░░░█████╗░░░░░░░██║╚█████╗░██║░░██║██╔██╗██║██║░░██║██████╦╝░░░██████╔╝░╚████╔╝░
██║░░░░░██║░░░██║░░░██╔══╝░░██╗░░██║░╚═══██╗██║░░██║██║╚████║██║░░██║██╔══██╗░░░██╔═══╝░░░╚██╔╝░░
███████╗██║░░░██║░░░███████╗╚█████╔╝██████╔╝╚█████╔╝██║░╚███║██████╔╝██████╦╝██╗██║░░░░░░░░██║░░░
╚══════╝╚═╝░░░╚═╝░░░╚══════╝░╚════╝░╚═════╝░░╚════╝░╚═╝░░╚══╝╚═════╝░╚═════╝░╚═╝╚═╝░░░░░░░░╚═╝░░░
"""

import json
import os
import base64
import logging
import shutil
from typing import Any, Dict, Optional, Union
from .utils import (
    convert_to_datetime, get_or_default, key_exists_or_add, normalize_keys,
    flatten_json, filter_data, sort_data, hash_password, check_password,
    sanitize_output, pretty_print
)
from .modules.search import search_data
from .modules.tgbot import BackupToTelegram
from .modules.csv import CSVExporter

# ---  Importations pour le chiffrement PyCryptodome ---
from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes
from Cryptodome.Protocol.KDF import PBKDF2
from Cryptodome.Util.Padding import pad, unpad

# LET'S CREATE THE DATABASE FILE
DATABASE_DIR = 'database'
if not os.path.exists(DATABASE_DIR):
    try:
        os.makedirs(DATABASE_DIR)
    except OSError as e:
        print(f"\033[91mOops! Unable to create the database directory. Make sure you have the correct permissions.\033[0m")
        print(f"\033[93mError details: {e}\033[0m")
        raise

# LOGGING
logging.basicConfig(filename=os.path.join(DATABASE_DIR, 'LiteJsonDb.log'), level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class JsonDB:
    def __init__(self, filename="db.json", backup_filename="db_backup.json", encryption_method="base64", encryption_key=None):
        self.filename = os.path.join(DATABASE_DIR, filename)
        self.backup_filename = os.path.join(DATABASE_DIR, backup_filename)
        self.encryption_method = encryption_method.lower()
        self.encryption_key = encryption_key
        self.db = {}
        self.observers = {}
        self.csv_exporter = CSVExporter(DATABASE_DIR)
        self._load_db()

        if self.encryption_method == "aes" and self.encryption_key is None:
          raise ValueError("Pour le chiffrement AES, une clé de chiffrement (encryption_key) est nécessaire.")

    # ==================================================
    #               ENCRYPTION/DECRYPTION
    # --------------------------------------------------
    def _encrypt(self, data: Dict[str, Any]) -> str:
        """Chiffre les données en utilisant la méthode sélectionnée."""
        if self.encryption_method == "base64":
          return self._base64_encrypt(data)
        elif self.encryption_method == "aes":
          return self._aes_encrypt(data)
        else:
          return json.dumps(data) # Pas de chiffrement

    def _decrypt(self, encoded_data: str) -> Dict[str, Any]:
        """Déchiffre les données en utilisant la méthode sélectionnée."""
        if self.encryption_method == "base64":
          return self._base64_decrypt(encoded_data)
        elif self.encryption_method == "aes":
          return self._aes_decrypt(encoded_data)
        else:
          return json.loads(encoded_data)

    def _base64_encrypt(self, data: Dict[str, Any]) -> str:
        """Encode data to base64."""
        json_data = json.dumps(data).encode('utf-8')
        encoded_data = base64.b64encode(json_data).decode('utf-8')
        return encoded_data

    def _base64_decrypt(self, encoded_data: str) -> Dict[str, Any]:
        """Decode data from base64."""
        decoded_data = base64.b64decode(encoded_data.encode('utf-8')).decode('utf-8')
        return json.loads(decoded_data)

    def _aes_encrypt(self, data: Dict[str, Any]) -> str:
        """Chiffre les données avec AES."""
        cipher, salt = self._create_aes_cipher(self.encryption_key)
        json_data = json.dumps(data).encode('utf-8')
        padded_data = pad(json_data, AES.block_size)
        ciphertext = cipher.encrypt(padded_data)
        # On retourne le sel, le IV et les données chiffrées, séparés par des ":"
        return f"{base64.b64encode(salt).decode('utf-8')}:{base64.b64encode(cipher.iv).decode('utf-8')}:{base64.b64encode(ciphertext).decode('utf-8')}"

    def _aes_decrypt(self, encoded_data: str) -> Dict[str, Any]:
        """Déchiffre les données avec AES."""
        salt_b64, iv_b64, ciphertext_b64 = encoded_data.split(":")
        salt = base64.b64decode(salt_b64)
        iv = base64.b64decode(iv_b64)
        ciphertext = base64.b64decode(ciphertext_b64)
        cipher = self._get_aes_cipher(self.encryption_key, salt, iv)
        decrypted_data = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return json.loads(decrypted_data.decode('utf-8'))

    def _create_aes_cipher(self, key: str):
      """Crée un cipher AES avec une clé dérivée du mot de passe."""
      salt = get_random_bytes(16)
      derived_key = PBKDF2(key, salt, dkLen=32, count=1000000)  # Dérivation de clé
      cipher = AES.new(derived_key, AES.MODE_CBC)
      return cipher, salt

    def _get_aes_cipher(self, key: str, salt: bytes, iv: bytes):
      """Récupère un cipher AES à partir du sel et du nonce."""
      derived_key = PBKDF2(key, salt, dkLen=32, count=1000000) # Dérivation de clé identique
      cipher = AES.new(derived_key, AES.MODE_CBC, iv=iv)
      return cipher

    # ==================================================
    #               DATABASE OPERATIONS
    #           SAVE, RESTORE, AND RETRIEVE
    # ==================================================
    def _load_db(self) -> None:
        """Load the database from the JSON file, or create a new one if it doesn't exist."""
        if not os.path.exists(self.filename):
            try:
                with open(self.filename, 'w') as file:
                    json.dump({}, file)
            except OSError as e:
                print(f"\033[91mOops! Unable to create the database file. Make sure you have the correct permissions.\033[0m")
                print(f"\033[93mError details: {e}\033[0m")
                raise
        try:
            with open(self.filename, 'r') as file:
                data = json.load(file)
                if data:
                    self.db = self._decrypt(data)
                else:
                    self.db = data
        except (OSError, json.JSONDecodeError) as e:
            print(f"\033[91mOops! Unable to load the database file. Make sure the file is accessible and contains valid JSON.\033[0m")
            print(f"\033[93mError details: {e}\033[0m")
            raise

    def _save_db(self) -> None:
        """Save the database to the JSON file."""
        try:
            data = self._encrypt(self.db)
            with open(self.filename, 'w') as file:
                json.dump(data, file, indent=4)
            logging.info(f"Database saved to {self.filename}")
        except OSError as e:
            print(f"\033[91mOops! Unable to save the database file. Make sure you have the correct permissions.\033[0m")
            print(f"\033[93mError details: {e}\033[0m")
            raise

    def _backup_db(self) -> None:
        """Create a backup of the database."""
        try:
            shutil.copy(self.filename, self.backup_filename)
            logging.info(f"Backup created: {self.backup_filename}")
        except OSError as e:
            print(f"\033[91mOops! Unable to create the backup file. Make sure you have the correct permissions.\033[0m")
            print(f"\033[93mError details: {e}\033[0m")
            raise

    def backup_to_telegram(self, token: str, chat_id: str):
        """Create db backup using Telegram API"""
        self._save_db()
        telegram_bot = BackupToTelegram(token=token, chat_id=chat_id)
        telegram_bot.backup_to_telegram(self.filename)

    def _restore_db(self) -> None:
        """Restore the database from backup."""
        if os.path.exists(self.backup_filename):
            try:
                shutil.copy(self.backup_filename, self.filename)
                self._load_db()
                logging.info(f"Database restored from backup: {self.backup_filename}")
            except OSError as e:
                print(f"\033[91mOops! Unable to restore the database from backup. Make sure the backup file is accessible.\033[0m")
                print(f"\033[93mError details: {e}\033[0m")
                raise
        else:
            print(f"\033[91mOops! No backup file found to restore.\033[0m")
            logging.error("No backup file found to restore.")

    # ==================================================
    #                EXPORT TO CSV
    # --------------------------------------------------
    # Exports either a specified collection or the entire
    # database to a CSV file.
    # ==================================================
    def export_to_csv(self, data_key: Optional[str] = None):
        if data_key:
            if data_key in self.db:
                data = self.db[data_key]
                csv_path = self.csv_exporter.export(data, f"{data_key}_export.csv")
                if csv_path:
                    print(f"\033[92mFile created: {csv_path}\033[0m")
                else:
                    print(f"\033[91mOops! Could not export '{data_key}' to CSV.\033[0m")
            else:
                print(f"\033[91mOops! The key '{data_key}' does not exist. Make sure the key is correct.\033[0m")
                print(f"\033[93mTip: Use a valid key path like 'users' to get specific user data.\033[0m")
        else:
            if self.db:
                csv_path = self.csv_exporter.export(self.db, "full_database_export.csv")
                if csv_path:
                    print(f"\033[92mFile created: {csv_path}\033[0m")
                else:
                    print("\033[91mOops! Could not export the database to CSV.\033[0m")
            else:
                print("\033[91mOops! The database is empty. Nothing to export.\033[0m")

    # ==================================================
    #                DATA VALIDATION
    # --------------------------------------------------
    # ==================================================

    def validate_data(self, data: Any) -> bool:
        """Validate data before insertion."""
        if isinstance(data, dict):
            # Check for duplicate keys with different types
            types = {}
            for key, value in data.items():
                if not isinstance(key, str):
                    print(f"\033[91mOops! Keys in data should be strings. Found non-string key '{key}'.\033[0m")
                    return False
                if key in types and types[key] != type(value):
                    print(f"\033[91mOops! Key '{key}' has conflicting types in data. Found types: {types[key]} and {type(value)}.\033[0m")
                    return False
                types[key] = type(value)
            # Ensure values are of allowed types
            return all(isinstance(value, (str, int, float, list, dict, bool, None)) for value in data.values())
        print(f"\033[91mOops! Data should be a dictionary.\033[0m")
        return False

    def _set_child(self, parent: Dict[str, Any], child_key: str, value: Any) -> None:
        """Helper to set data in a nested dictionary."""
        keys = child_key.split('/')
        for key in keys[:-1]:
            parent = parent.setdefault(key, {})
        parent[keys[-1]] = value

    def _merge_dicts(self, dict1, dict2):
        """Merge dict2 into dict1."""
        for key, value in dict2.items():
            if isinstance(value, dict) and key in dict1 and isinstance(dict1[key], dict):
                self._merge_dicts(dict1[key], value)
            else:
                dict1[key] = value
        return dict1

    def key_exists(self, key: str) -> bool:
        """Check if a key exists in the database."""
        keys = key.split('/')
        data = self.db
        for k in keys:
            if k in data:
                data = data[k]
            else:
                return False
        return True

    def get_data(self, key: str) -> Optional[Any]:
        """Get data from the database by key."""
        keys = key.split('/')
        data = self.db
        for k in keys:
            if k in data:
                data = data[k]
            else:
                print(f"\033[91mOops! The key '{key}' does not exist. Make sure the key is correct.\033[0m")
                print(f"\033[93mTip: Use a valid key path like 'users/1' to get specific user data.\033[0m")
                return None
        return data

    def set_data(self, key: str, value: Optional[Any] = None) -> None:
        """Set data in the database and notify observers.
    
        If `value` is not provided, initialize the key with an empty dictionary.
        """
        if value is None:
            value = {}

        if not self.validate_data(value):
            print("\033[91mOops! The provided data is not in a valid format. Use a dictionary with consistent types.\033[0m")
            print(f"\033[93mTip: Ensure keys have consistent types and values are of allowed types.\033[0m")
            return
        if self.key_exists(key):
            print(f"\033[91mOops! The key '{key}' already exists. Use 'edit_data' to modify the existing key.\033[0m")
            print(f"\033[93mTip: If you want to update or add new key, use db.edit_data('{key}', new_value).\033[0m")
            return
        self._set_child(self.db, key, value)
        self.notify_observers("set_data", key, value)
        self._backup_db()
        self._save_db()

    def edit_data(self, key: str, value: Any) -> None:
        """Edit data in the database and notify observers."""
        if not self.key_exists(key):
            print(f"\033[91mOops! The key '{key}' does not exist. Unable to edit non-existent data.\033[0m")
            print(f"\033[93mTip: Use 'set_data' to add new data if needed.\033[0m")
            return
        if not self.validate_data(value):
            print("\033[91mOops! The provided data is not in a valid format. Use a dictionary with consistent types.\033[0m")
            print(f"\033[93mTip: Ensure keys have consistent types and values are of allowed types.\033[0m")
            return

        keys = key.split('/')
        data = self.db
        for k in keys[:-1]:
            data = data.setdefault(k, {})
    
        current_data = data.get(keys[-1], {})
    
        """
        Adding the increment because we're all about making coding a little bit easier. 
        (Plus, who doesn't love a good shortcut?)
        """
        if isinstance(value, dict) and "increment" in value:
            for field, increment_value in value["increment"].items():
                if field in current_data:
                    if isinstance(current_data[field], (int, float)):
                        if isinstance(increment_value, (int, float)):
                            current_data[field] += increment_value
                        else:
                            print(f"\033[91mOops! The increment value for '{field}' is not a number.\033[0m")
                            print(f"\033[93mTip: Make sure to provide a numeric value for incrementing. Example: db.edit_data('users/1', {{'increment': {{'score': 5}}}})\033[0m")
                            return
                    else:
                        print(f"\033[91mOops! The field '{field}' is not a number in '{key}'. Cannot increment.\033[0m")
                        print(f"\033[93mTip: Ensure that the field '{field}' exists and is a number before incrementing.\033[0m")
                        return
                else:
                    print(f"\033[91mOops! The field '{field}' does not exist in '{key}'. Cannot increment.\033[0m")
                    print(f"\033[93mTip: Make sure the field exists in the data structure. You can use db.edit_data to set initial values.\033[0m")
                    return
        else:
            if isinstance(current_data, dict):
                value = self._merge_dicts(current_data, value)
            data[keys[-1]] = value

        self._backup_db()
        self._save_db()
    
    # ==================================================
    #                DATA OBSERVERS
    # --------------------------------------------------
    # ==================================================

    def add_observer(self, key: str, observer_func) -> None:
        """Add an observer for a specific key."""
        if key not in self.observers:
            self.observers[key] = []
        self.observers[key].append(observer_func)

    def remove_observer(self, key: str, observer_func) -> None:
        """Remove an observer for a specific key."""
        if key in self.observers:
            self.observers[key].remove(observer_func)
            if not self.observers[key]:
                del self.observers[key]

    def notify_observers(self, action: str, key: str, value: Any) -> None:
        """Notify all observers about a change."""
        for observer_key, observers in self.observers.items():
            if key.startswith(observer_key):
                for observer in observers:
                    observer(action, key, value)

    def remove_data(self, key: str) -> None:
        """Remove data from the database by key."""
        keys = key.split('/')
        data = self.db
        for k in keys[:-1]:
            if k in data:
                data = data[k]
            else:
                print(f"\033[91mOops! The key '{key}' does not exist. Cannot delete.\033[0m")
                print(f"\033[93mTip: Make sure the key path is correct and exists.\033[0m")
                return
        if keys[-1] in data:
            del data[keys[-1]]
            self._backup_db()
            self._save_db()
        else:
            print(f"\033[91mOops! The key '{key}' does not exist. Cannot delete.\033[0m")
            print(f"\033[93mTip: Make sure the key path is correct and exists.\033[0m")

    # ==================================================
    #                WHOLE DATABASE
    # --------------------------------------------------
    # ==================================================

    def get_db(self, raw: bool = False) -> Union[Dict[str, Any], str]:
        """Get the entire database, optionally in raw format."""
        if raw:
            return self.db
        if self.encryption_method != "none":
          return self._decrypt(self._encrypt(self.db))
        return self.db

    # ==================================================
    #            SUBCOLLECTION VALIDATION
    # --------------------------------------------------
    # ==================================================

    def get_subcollection(self, collection_name: str, item_id: Optional[str] = None) -> Optional[Any]:
        """Get a specific subcollection or an item within a subcollection."""
        collection = self.db.get(collection_name, {})
        if item_id is not None:
            if item_id in collection:
                return collection[item_id]
            else:
                print(f"\033[91mOops! The ID '{item_id}' does not exist in the collection '{collection_name}'.\033[0m")
                print(f"\033[93mTip: Check if the ID is correct. Use get_subcollection('{collection_name}') to see all items.\033[0m")
                return None
        return collection

    def set_subcollection(self, collection_name: str, item_id: str, value: Any) -> None:
        """Set an item in a specific subcollection."""
        if not self.validate_data(value):
            print("\033[91mOops! The provided data is not in a valid format. Use a dictionary.\033[0m")
            print(f"\033[93mTip: Your data should look like this: {{'name': 'Aliou', 'age': 30}}\033[0m")
            return
        if collection_name not in self.db:
            self.db[collection_name] = {}
        if item_id in self.db[collection_name]:
            print(f"\033[91mOops! The ID '{item_id}' already exists in the collection '{collection_name}'. Use 'edit_subcollection' to modify the existing item.\033[0m")
            print(f"\033[93mTip: If you want to update or add new item, use db.edit_subcollection('{collection_name}', '{item_id}', new_value).\033[0m")
            return
        self.db[collection_name][item_id] = value
        self._backup_db()
        self._save_db()

    def edit_subcollection(self, collection_name: str, item_id: str, value: Any) -> None:
        """Edit an item in a specific subcollection."""
        if not self.validate_data(value):
            print("\033[91mOops! The provided data is not in a valid format. Use a dictionary.\033[0m")
            print(f"\033[93mTip: Your data should look like this: {{'name': 'Aliou', 'age': 30}}\033[0m")
            return
        if collection_name in self.db and item_id in self.db[collection_name]:
            current_data = self.db[collection_name][item_id]
            if isinstance(current_data, dict):
                value = self._merge_dicts(current_data, value)
            self.db[collection_name][item_id] = value
            self._backup_db()
            self._save_db()
        else:
            print(f"\033[91mOops! The ID '{item_id}' does not exist in the collection '{collection_name}'. Unable to edit non-existent item.\033[0m")
            print(f"\033[93mTip: Use 'set_subcollection' to create a new item if needed.\033[0m")

    def remove_subcollection(self, collection_name: str, item_id: Optional[str] = None) -> None:
        """Remove an entire subcollection or a specific item within it."""
        if item_id is None:
            if collection_name in self.db:
                del self.db[collection_name]
                self._backup_db()
                self._save_db()
            else:
                print(f"\033[91mOops! The collection '{collection_name}' does not exist. Cannot delete.\033[0m")
                print(f"\033[93mTip: Make sure the collection name is correct.\033[0m")
                return
        else:
            if collection_name in self.db and item_id in self.db[collection_name]:
                del self.db[collection_name][item_id]
                self._backup_db()
                self._save_db()
            else:
                print(f"\033[91mOops! The ID '{item_id}' does not exist in the collection '{collection_name}'. Cannot delete.\033[0m")
                print(f"\033[93mTip: Check the ID and collection name. Use get_subcollection('{collection_name}') to see all items.\033[0m")
                return

    # ==================================================
    #                DATA SEARCH
    # ==================================================

    def search_data(self, value: Any, key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Search for a value in the database.

        :param value: The elusive treasure you're hunting for.
        :param key: A specific key to search within the documents. If None, we'll search everywhere like a treasure map with no boundaries.
        :return: A dictionary of found items or None if the treasure remains hidden.
        """

        try:
            result = search_data(self.db, value, key)
            if result:
                return result
            else:
                return None
        except Exception as e:
            print(f"\033[91mOops! An error occurred while searching data.\033[0m")
            print(f"\033[93mError details: {e}\033[0m")
            return None
    
    # ==================================================
    #               UTILITY FUNCTIONS
    #         (Methods for commonly used utilities)
    # --------------------------------------------------
    # This section provides static methods that act as
    # wrappers for various utility functions. They are
    # designed to be used across different parts of the
    # application for convenience and consistency.
    # ==================================================

    @staticmethod
    def call_utility_function(func_name, *args, **kwargs):
        functions = {
            'convert_to_datetime': convert_to_datetime,
            'get_or_default': get_or_default,
            'key_exists_or_add': key_exists_or_add,
            'normalize_keys': normalize_keys,
            'flatten_json': flatten_json,
            'filter_data': filter_data,
            'sort_data': sort_data,
            'hash_password': hash_password,
            'check_password': check_password,
            'sanitize_output': sanitize_output,
            'pretty_print': pretty_print
        }
        if func_name in functions:
            return functions[func_name](*args, **kwargs)
        raise ValueError(f"Function {func_name} not found.")
    
    @staticmethod
    def convert_to_datetime(date_str):
        return JsonDB.call_utility_function('convert_to_datetime', date_str)

    @staticmethod
    def get_or_default(data, key, default=None):
        return JsonDB.call_utility_function('get_or_default', data, key, default)

    @staticmethod
    def key_exists_or_add(data, key, default):
        return JsonDB.call_utility_function('key_exists_or_add', data, key, default)

    @staticmethod
    def normalize_keys(data):
        return JsonDB.call_utility_function('normalize_keys', data)

    @staticmethod
    def flatten_json(data):
        return JsonDB.call_utility_function('flatten_json', data)

    @staticmethod
    def filter_data(data, condition):
        return JsonDB.call_utility_function('filter_data', data, condition)

    @staticmethod
    def sort_data(data, key, reverse=False):
        return JsonDB.call_utility_function('sort_data', data, key, reverse)

    @staticmethod
    def hash_password(password):
        return JsonDB.call_utility_function('hash_password', password)

    @staticmethod
    def check_password(stored_hash, password):
        return JsonDB.call_utility_function('check_password', stored_hash, password)

    @staticmethod
    def sanitize_output(data):
        return JsonDB.call_utility_function('sanitize_output', data)

    @staticmethod
    def pretty_print(data):
        return JsonDB.call_utility_function('pretty_print', data)

    def migrate_data(self, new_encryption_method: str, new_encryption_key: Optional[str] = None) -> None:
        """Migre les données vers une nouvelle méthode de chiffrement."""
        if new_encryption_method == "aes" and new_encryption_key is None:
            raise ValueError("Pour le chiffrement AES, une clé de chiffrement (new_encryption_key) est nécessaire.")

        
        decrypted_data = self._decrypt(self._encrypt(self.db))

        
        self.encryption_method = new_encryption_method
        self.encryption_key = new_encryption_key

        
        self.db = self._decrypt(self._encrypt(decrypted_data))

        
        self._save_db()
        print(f"Données migrées vers la méthode de chiffrement : {new_encryption_method}")