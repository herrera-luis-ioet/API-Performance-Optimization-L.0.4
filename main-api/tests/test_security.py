import pytest
from app.core.security import verify_password, get_password_hash, pwd_context

def test_password_hashing():
    """Test that password hashing works correctly"""
    password = "mysecretpassword"
    hashed = get_password_hash(password)
    
    # Verify the hash is not the plain password
    assert hashed != password
    
    # Verify the hash starts with $argon2 indicating Argon2 was used
    assert hashed.startswith("$argon2")
    
    # Verify the same password hashes to different values (due to salt)
    assert get_password_hash(password) != get_password_hash(password)

def test_password_verification():
    """Test that password verification works correctly"""
    password = "mysecretpassword"
    hashed = get_password_hash(password)
    
    # Verify correct password matches
    assert verify_password(password, hashed) is True
    
    # Verify incorrect password doesn't match
    assert verify_password("wrongpassword", hashed) is False

def test_bcrypt_compatibility():
    """Test that the system can still verify bcrypt hashes"""
    # Create a new bcrypt hash
    password = "test_password"
    bcrypt_hash = pwd_context.hash(password, scheme="bcrypt")
    
    # Test verification still works with bcrypt hash
    assert verify_password(password, bcrypt_hash) is True
    assert verify_password("wrong_password", bcrypt_hash) is False

def test_hash_migration():
    """Test that bcrypt hashes are automatically upgraded to Argon2"""
    password = "test_password"
    # Create a bcrypt hash
    bcrypt_hash = pwd_context.hash(password, scheme="bcrypt")
    
    # Verify the password first
    assert verify_password(password, bcrypt_hash) is True
    
    # Hash the same password with current settings
    new_hash = get_password_hash(password)
    
    # Verify the new hash is Argon2
    assert new_hash.startswith("$argon2")

def test_invalid_password_scenarios():
    """Test various invalid password scenarios"""
    # Test verification with None password
    with pytest.raises(TypeError):
        get_password_hash(None)
        
    # Test verification with empty password
    assert not verify_password("", get_password_hash("test"))
    
    # Test verification with empty hash
    assert not verify_password("password", "")
    
    # Test verification with invalid hash format
    assert not verify_password("password", "invalid_hash_format")

def test_argon2_parameters():
    """Test that Argon2 parameters are correctly configured"""
    # Verify Argon2 is the default scheme
    assert pwd_context.default_scheme() == "argon2"
    
    # Create a hash and verify it starts with argon2
    test_hash = get_password_hash("test")
    assert test_hash.startswith("$argon2")
    
    # Verify the hash can be used for verification
    assert verify_password("test", test_hash)
