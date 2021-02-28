"""
Custom manager class
"""
from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """[Custom user model]

    Arguments:
        BaseUserManager {[type]} -- [description]

    Raises:
        ValueError: [description]
        ValueError: [description]

    Returns:
        [type] -- [description]
    """

    def create_user(self, username, email=None, password=None, **data):
        """
        Create user
        """
        data.setdefault('is_staff', False)
        data.setdefault('is_superuser', False)
        return self._create_user(username, email, password, data)

    def create_superuser(self, username, email=None, password=None, **data):
        """
        Create super user
        """
        data.setdefault('is_staff', True)
        data.setdefault('is_superuser', True)
        if data.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        return self._create_user(username, email, password, data)

    def _create_user(self, username, email, password, data):
        """
        Create and save a user with the given username, email, and password.
        """
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        is_staff = data.get('is_staff')
        is_superuser = data.get('is_superuser')
        if not username:
            raise ValueError('The given username must be set')
        email = self.normalize_email(email)
        username = self.model.normalize_username(username)
        user = self.model(username=username, email=email, first_name=first_name, last_name=last_name, is_staff=is_staff,
                          is_superuser=is_superuser)
        user.set_password(password)
        user.save(using=self._db)
        return user
