import bcrypt

password = b"password123"
salt = bcrypt.gensalt()
hashed = bcrypt.hashpw(password, salt)

# Print as a string
print(hashed.decode('utf-8'))
