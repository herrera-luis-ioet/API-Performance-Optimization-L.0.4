from passlib.context import CryptContext

# PUBLIC_INTERFACE
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated=["bcrypt"],
    argon2__rounds=4,  # Number of iterations
    argon2__memory_cost=65536,  # Memory usage in kibibytes (64MB)
    argon2__parallelism=4,  # Number of parallel threads
    argon2__salt_size=16,  # Salt size in bytes
    argon2__hash_len=32,  # Hash length in bytes
)

# PUBLIC_INTERFACE
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        plain_password: The plaintext password to verify
        hashed_password: The hashed password to verify against
        
    Returns:
        bool: True if the password matches, False otherwise
    """
    if not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except:
        return False

# PUBLIC_INTERFACE
def get_password_hash(password: str) -> str:
    """
    Generate a secure password hash using Argon2.
    
    Args:
        password: The plaintext password to hash
        
    Returns:
        str: The hashed password
    """
    return pwd_context.hash(password)
