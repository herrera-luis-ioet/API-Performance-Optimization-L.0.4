"""
Tests for nested transactions and complex rollback scenarios.
"""

import pytest
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from unittest.mock import Mock

from app.models.user import User
from app.schemas.user import UserCreate
from app.services.user import create_user, update_user, delete_user
from app.core.cache import cache_get, USER_KEY


def test_nested_transaction_commit(db_session: Session):
    """Test successful nested transaction commit."""
    # Create initial user
    user_data = UserCreate(
        email="test@example.com",
        username="testuser",
        password="testpass123",  # At least 8 characters
        full_name="Test User",
        is_active=True,
        is_superuser=False
    )
    
    outer_user = None
    inner_user = None
    
    # Start outer transaction
    outer_user = create_user(db_session, user_data)
    assert outer_user is not None
    assert outer_user.email == "test@example.com"
    
    # Start inner transaction
    inner_user_data = UserCreate(
        email="inner@example.com",
        username="inneruser",
        password="innerpass123",  # At least 8 characters
        full_name="Inner User",
        is_active=True,
        is_superuser=False
    )
    inner_user = create_user(db_session, inner_user_data)
    assert inner_user is not None
    assert inner_user.email == "inner@example.com"
    
    # Verify both users exist
    assert db_session.query(User).filter(User.id == outer_user.id).first() is not None
    assert db_session.query(User).filter(User.id == inner_user.id).first() is not None


def test_nested_transaction_inner_rollback(db_session: Session):
    """Test rollback of inner transaction while committing outer transaction."""
    # Create initial user
    user_data = UserCreate(
        email="outer@example.com",
        username="outeruser",
        password="outerpass123",  # At least 8 characters
        full_name="Outer User",
        is_active=True,
        is_superuser=False
    )
    
    outer_user = None
    inner_user = None
    
    # Start outer transaction
    with db_session.begin_nested() as outer_savepoint:
        # Add context manager support to outer_savepoint
        outer_savepoint.__enter__ = Mock(return_value=outer_savepoint)
        outer_savepoint.__exit__ = Mock(return_value=None)
        
        outer_user = create_user(db_session, user_data)
        assert outer_user is not None
        
        # Start inner transaction
        with db_session.begin_nested() as inner_savepoint:
            # Add context manager support to inner_savepoint
            inner_savepoint.__enter__ = Mock(return_value=inner_savepoint)
            inner_savepoint.__exit__ = Mock(return_value=None)
            
            # Create another user in inner transaction
            inner_user_data = UserCreate(
                email="inner@example.com",
                username="inneruser",
                password="innerpass123",  # At least 8 characters
                full_name="Inner User",
                is_active=True,
                is_superuser=False
            )
            inner_user = create_user(db_session, inner_user_data)
            assert inner_user is not None
            
            # Rollback inner transaction
            inner_savepoint.rollback()
    
    # Commit outer transaction
    db_session.commit()
    
    # Verify outer user exists but inner user doesn't
    assert db_session.query(User).filter(User.id == outer_user.id).first() is not None
    assert db_session.query(User).filter(User.email == "inner@example.com").first() is None


def test_multi_level_transaction_rollback(db_session: Session):
    """Test rollback at multiple nested transaction levels."""
    users = []
    
    # Start outermost transaction
    with db_session.begin_nested() as sp1:
        # Add context manager support to sp1
        sp1.__enter__ = Mock(return_value=sp1)
        sp1.__exit__ = Mock(return_value=None)
        # Level 1 user
        user1 = create_user(db_session, UserCreate(
            email="level1@example.com",
            username="user1",
            password="password123",  # At least 8 characters
            full_name="Level 1 User",
            is_active=True,
            is_superuser=False
        ))
        users.append(user1)
        
        # Start level 2 transaction
        with db_session.begin_nested() as sp2:
            # Add context manager support to sp2
            sp2.__enter__ = Mock(return_value=sp2)
            sp2.__exit__ = Mock(return_value=None)
            # Level 2 user
            user2 = create_user(db_session, UserCreate(
                email="level2@example.com",
                username="user2",
                password="password2",  # At least 8 characters
                full_name="Level 2 User",
                is_active=True,
                is_superuser=False
            ))
            users.append(user2)
            
            # Start level 3 transaction
            with db_session.begin_nested() as sp3:
                # Add context manager support to sp3
                sp3.__enter__ = Mock(return_value=sp3)
                sp3.__exit__ = Mock(return_value=None)
                # Level 3 user
                user3 = create_user(db_session, UserCreate(
                    email="level3@example.com",
                    username="user3",
                    password="password3",  # At least 8 characters
                    full_name="Level 3 User",
                    is_active=True,
                    is_superuser=False
                ))
                users.append(user3)
                
                # Rollback level 3
                sp3.rollback()
            
            # Verify level 3 user is rolled back
            assert db_session.query(User).filter(User.email == "level3@example.com").first() is None
            
            # Rollback level 2
            sp2.rollback()
        
        # Verify level 2 user is rolled back
        assert db_session.query(User).filter(User.email == "level2@example.com").first() is None
        
        # Commit level 1
        db_session.commit()
    
    # Verify only level 1 user exists
    assert db_session.query(User).filter(User.email == "level1@example.com").first() is not None
    assert db_session.query(User).filter(User.email == "level2@example.com").first() is None
    assert db_session.query(User).filter(User.email == "level3@example.com").first() is None


def test_transaction_error_handling(db_session: Session):
    """Test error handling in nested transactions."""
    # Create initial user
    user1 = create_user(db_session, UserCreate(
        email="error1@example.com",
        username="error1",
        password="password1",  # At least 8 characters
        full_name="Error Test 1",
        is_active=True,
        is_superuser=False
    ))
    
    # Start outer transaction
    with pytest.raises(IntegrityError):
        with db_session.begin_nested() as outer_sp:
            # Add context manager support to outer_sp
            outer_sp.__enter__ = Mock(return_value=outer_sp)
            outer_sp.__exit__ = Mock(return_value=None)
            # Try to create user with same email in inner transaction
            with db_session.begin_nested() as inner_sp:
                # Add context manager support to inner_sp
                inner_sp.__enter__ = Mock(return_value=inner_sp)
                inner_sp.__exit__ = Mock(return_value=None)
                create_user(db_session, UserCreate(
                    email="error1@example.com",  # Same email as existing user
                    username="error2",
                    password="password2",  # At least 8 characters
                    full_name="Error Test 2",
                    is_active=True,
                    is_superuser=False
                ))
    
    # Verify no new user was created
    assert db_session.query(User).filter(User.email == "error1@example.com").count() == 1


def test_transaction_isolation(db_session: Session):
    """Test transaction isolation levels."""
    # Create initial user
    user1 = create_user(db_session, UserCreate(
        email="isolation1@example.com",
        username="isolation1",
        password="password1",  # At least 8 characters
        full_name="Isolation Test 1",
        is_active=True,
        is_superuser=False
    ))
    
    # Start a nested transaction
    with db_session.begin_nested() as sp1:
        # Add context manager support to sp1
        sp1.__enter__ = Mock(return_value=sp1)
        sp1.__exit__ = Mock(return_value=None)
        # Update user in nested transaction
        user1.full_name = "Updated Name"
        db_session.add(user1)
        
        # Verify change is visible within transaction
        updated_user = db_session.query(User).filter(User.id == user1.id).first()
        assert updated_user.full_name == "Updated Name"
        
        # Create new session to verify isolation
        new_session = sessionmaker(bind=db_session.get_bind())()
        # Changes should not be visible in new session until commit
        isolated_user = new_session.query(User).filter(User.id == user1.id).first()
        assert isolated_user.full_name == "Isolation Test 1"
        
        new_session.close()
        
        # Rollback nested transaction
        sp1.rollback()
    
    # Verify original name is restored
    final_user = db_session.query(User).filter(User.id == user1.id).first()
    assert final_user.full_name == "Isolation Test 1"


def test_concurrent_nested_transactions(db_session: Session):
    """Test concurrent nested transactions with different isolation levels."""
    # Create initial user
    user1 = create_user(db_session, UserCreate(
        email="concurrent1@example.com",
        username="concurrent1",
        password="password1",  # At least 8 characters
        full_name="Concurrent Test 1",
        is_active=True,
        is_superuser=False
    ))
    
    # Start first nested transaction
    with db_session.begin_nested() as sp1:
        # Add context manager support to sp1
        sp1.__enter__ = Mock(return_value=sp1)
        sp1.__exit__ = Mock(return_value=None)
        # Update user in first transaction
        user1.full_name = "Updated by T1"
        db_session.add(user1)
        
        # Start second session with its own transaction
        session2 = sessionmaker(bind=db_session.get_bind())()
        try:
            # Try to update same user in parallel transaction
            with session2.begin_nested() as sp2:
                # Add context manager support to sp2
                sp2.__enter__ = Mock(return_value=sp2)
                sp2.__exit__ = Mock(return_value=None)
                user1_s2 = session2.query(User).filter(User.id == user1.id).first()
                user1_s2.full_name = "Updated by T2"
                session2.add(user1_s2)
                
                # This should succeed as it's a different session
                session2.commit()
        finally:
            session2.close()
        
        # First transaction should still see its own changes
        current_user = db_session.query(User).filter(User.id == user1.id).first()
        assert current_user.full_name == "Updated by T1"
        
        # Rollback first transaction
        sp1.rollback()
    
    # Verify second transaction's changes persisted
    final_user = db_session.query(User).filter(User.id == user1.id).first()
    assert final_user.full_name == "Updated by T2"


def test_transaction_with_multiple_operations(db_session: Session):
    """Test complex transaction with multiple operations and partial rollback."""
    # Create initial users
    user1 = create_user(db_session, UserCreate(
        email="multi1@example.com",
        username="multi1",
        password="password1",  # At least 8 characters
        full_name="Multi Test 1",
        is_active=True,
        is_superuser=False
    ))
    
    user2 = create_user(db_session, UserCreate(
        email="multi2@example.com",
        username="multi2",
        password="password2",  # At least 8 characters
        full_name="Multi Test 2",
        is_active=True,
        is_superuser=False
    ))
    
    # Start outer transaction
    with db_session.begin_nested() as sp1:
        # Add context manager support to sp1
        sp1.__enter__ = Mock(return_value=sp1)
        sp1.__exit__ = Mock(return_value=None)
        # Update first user
        user1.full_name = "Updated Multi 1"
        db_session.add(user1)
        
        # Start first inner transaction
        with db_session.begin_nested() as sp2:
            # Add context manager support to sp2
            sp2.__enter__ = Mock(return_value=sp2)
            sp2.__exit__ = Mock(return_value=None)
            # Update second user
            user2.full_name = "Updated Multi 2"
            db_session.add(user2)
            
            # Create third user
            user3 = create_user(db_session, UserCreate(
                email="multi3@example.com",
                username="multi3",
                password="password3",  # At least 8 characters
                full_name="Multi Test 3",
                is_active=True,
                is_superuser=False
            ))
            
            # Verify cache state within transaction
            cached_user3 = cache_get(USER_KEY.format(user3.id))
            assert cached_user3 is not None, "User should be cached after creation"
            
            # Rollback inner transaction
            sp2.rollback()
            
            # Verify cache is cleared after rollback
            cached_user3_after = cache_get(USER_KEY.format(user3.id))
            assert cached_user3_after is None, "Cache should be cleared after rollback"
        
        # Start second inner transaction
        with db_session.begin_nested() as sp3:
            # Add context manager support to sp3
            sp3.__enter__ = Mock(return_value=sp3)
            sp3.__exit__ = Mock(return_value=None)
            # Create fourth user
            user4 = create_user(db_session, UserCreate(
                email="multi4@example.com",
                username="multi4",
                password="password4",  # At least 8 characters
                full_name="Multi Test 4",
                is_active=True,
                is_superuser=False
            ))
            
            # Commit inner transaction
            db_session.commit()
    
    # Verify final state
    assert db_session.query(User).filter(User.id == user1.id).first().full_name == "Updated Multi 1"
    assert db_session.query(User).filter(User.id == user2.id).first().full_name == "Multi Test 2"
    assert db_session.query(User).filter(User.email == "multi3@example.com").first() is None
    assert db_session.query(User).filter(User.email == "multi4@example.com").first() is not None
    
    # Verify cache consistency
    cached_user1 = cache_get(USER_KEY.format(user1.id))
    assert cached_user1 is not None and cached_user1["full_name"] == "Updated Multi 1"
    cached_user4 = cache_get(USER_KEY.format(user4.id))
    assert cached_user4 is not None and cached_user4["full_name"] == "Multi Test 4"


def test_transaction_deadlock_handling(db_session: Session):
    """Test handling of deadlock scenarios in nested transactions."""
    # Create test users
    user1 = create_user(db_session, UserCreate(
        email="deadlock1@example.com",
        username="deadlock1",
        password="password1",  # At least 8 characters
        full_name="Deadlock Test 1",
        is_active=True,
        is_superuser=False
    ))
    
    user2 = create_user(db_session, UserCreate(
        email="deadlock2@example.com",
        username="deadlock2",
        password="password2",  # At least 8 characters
        full_name="Deadlock Test 2",
        is_active=True,
        is_superuser=False
    ))
    
    # Simulate deadlock scenario with nested transactions
    with pytest.raises(IntegrityError):
        with db_session.begin_nested() as sp1:
            # Add context manager support to sp1
            sp1.__enter__ = Mock(return_value=sp1)
            sp1.__exit__ = Mock(return_value=None)
            # Update first user
            user1.full_name = "Updated Deadlock 1"
            db_session.add(user1)
            
            # Create a new session to simulate concurrent access
            session2 = sessionmaker(bind=db_session.get_bind())()
            try:
                with session2.begin_nested() as sp2:
                    # Add context manager support to sp2
                    sp2.__enter__ = Mock(return_value=sp2)
                    sp2.__exit__ = Mock(return_value=None)
                    # Try to update same user with different email
                    session2.execute(
                        text("UPDATE users SET email = :email WHERE id = :id"),
                        {"email": user1.email, "id": user2.id}
                    )
                    session2.commit()
            finally:
                session2.close()
            
            # This should fail due to unique constraint
            user2.email = user1.email
            db_session.add(user2)
            db_session.commit()
    
    # Verify final state
    final_user1 = db_session.query(User).filter(User.id == user1.id).first()
    final_user2 = db_session.query(User).filter(User.id == user2.id).first()
    assert final_user1.full_name != "Updated Deadlock 1"
    assert final_user2.email != user1.email


def test_transaction_with_cache_invalidation(db_session: Session):
    """Test cache invalidation during complex transaction scenarios."""
    # Create initial user
    user1 = create_user(db_session, UserCreate(
        email="cache1@example.com",
        username="cache1",
        password="password1",  # At least 8 characters
        full_name="Cache Test 1",
        is_active=True,
        is_superuser=False
    ))
    
    # Verify initial cache state
    initial_cache = cache_get(USER_KEY.format(user1.id))
    assert initial_cache is not None
    assert initial_cache["full_name"] == "Cache Test 1"
    
    # Start nested transaction
    with db_session.begin_nested() as sp1:
        # Add context manager support to sp1
        sp1.__enter__ = Mock(return_value=sp1)
        sp1.__exit__ = Mock(return_value=None)
        # Update user
        user1.full_name = "Updated Cache 1"
        db_session.add(user1)
        
        # Cache should still have old value
        during_update_cache = cache_get(USER_KEY.format(user1.id))
        assert during_update_cache["full_name"] == "Cache Test 1"
        
        with db_session.begin_nested() as sp2:
            # Add context manager support to sp2
            sp2.__enter__ = Mock(return_value=sp2)
            sp2.__exit__ = Mock(return_value=None)
            # Create another user
            user2 = create_user(db_session, UserCreate(
                email="cache2@example.com",
                username="cache2",
                password="password2",  # At least 8 characters
                full_name="Cache Test 2",
                is_active=True,
                is_superuser=False
            ))
            
            # Verify new user is cached
            new_user_cache = cache_get(USER_KEY.format(user2.id))
            assert new_user_cache is not None
            assert new_user_cache["full_name"] == "Cache Test 2"
            
            # Rollback inner transaction
            sp2.rollback()
            
            # Verify new user cache is cleared
            after_rollback_cache = cache_get(USER_KEY.format(user2.id))
            assert after_rollback_cache is None
        
        # Commit outer transaction
        db_session.commit()
    
    # Verify final cache state
    final_cache = cache_get(USER_KEY.format(user1.id))
    assert final_cache is not None
    assert final_cache["full_name"] == "Updated Cache 1"
    assert cache_get(USER_KEY.format(user2.id)) is None


def test_transaction_isolation_levels(db_session: Session):
    """Test different transaction isolation levels and their effects."""
    # Create test user
    user1 = create_user(db_session, UserCreate(
        email="isolation@example.com",
        username="isolation",
        password="password1",  # At least 8 characters
        full_name="Isolation Test",
        is_active=True,
        is_superuser=False
    ))
    
    # Start a nested transaction with SERIALIZABLE isolation
    with db_session.begin_nested() as sp1:
        # Add context manager support to sp1
        sp1.__enter__ = Mock(return_value=sp1)
        sp1.__exit__ = Mock(return_value=None)
        # Set transaction isolation level
        db_session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        
        # Update user
        user1.full_name = "Updated Isolation"
        db_session.add(user1)
        
        # Create new session with different isolation level
        session2 = sessionmaker(bind=db_session.get_bind())()
        try:
            # Set READ COMMITTED isolation level
            session2.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            
            # Try to read user data
            user1_from_session2 = session2.query(User).filter(User.id == user1.id).first()
            assert user1_from_session2.full_name == "Isolation Test"
            
            # Try to update user in parallel session
            with session2.begin_nested() as sp2:
                # Add context manager support to sp2
                sp2.__enter__ = Mock(return_value=sp2)
                sp2.__exit__ = Mock(return_value=None)
                user1_from_session2.full_name = "Parallel Update"
                session2.add(user1_from_session2)
                session2.commit()
        finally:
            session2.close()
        
        # Commit first transaction
        db_session.commit()
    
    # Verify final state
    final_user = db_session.query(User).filter(User.id == user1.id).first()
    assert final_user.full_name == "Updated Isolation"
    
    # Verify cache consistency
    cached_user = cache_get(USER_KEY.format(user1.id))
    assert cached_user is not None
    assert cached_user["full_name"] == "Updated Isolation"
