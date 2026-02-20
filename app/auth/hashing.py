## Password hashing utilities

import bcrypt

def hash_password(password: str) -> str:
    # bcrypt has a 72-byte limit, truncate if necessary
    password_bytes = password[:72].encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    # bcrypt has a 72-byte limit, truncate if necessary
    password_bytes = password[:72].encode('utf-8')
    hash_bytes = password_hash.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hash_bytes)