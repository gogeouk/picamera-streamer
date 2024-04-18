import os

def get_env_var(key, default=None):
  """
  Retrieves an environment variable, prioritizing system environment 
  variables over values from the .env file (if it exists).

  Args:
      key (str): The name of the environment variable to retrieve.
      default (str, optional): A default value to return if the key is not found 
          in either system environment or .env file. Defaults to None.

  Returns:
      str: The value of the environment variable, or the provided default value 
           if not found.
  """
  # Check system environment variables first
  value = os.getenv(key)
  if value:
    return value

  # If not found in system environment, try reading from .env file
  try:
    with open(".env", "r") as f:
      for line in f:
        if not line.strip() or line.startswith("#"):
          continue
        key_env, value_env = line.strip().split("=")
        if key_env == key:
          return value_env
  except FileNotFoundError:
    pass  # Ignore if .env file doesn't exist
  return default

""" Example Usage
api_key = get_env_var("API_KEY", "your_default_key")
if api_key:
  print(f"API Key: {api_key}")
else:
  print("API_KEY not found in environment or .env file, using default")
"""