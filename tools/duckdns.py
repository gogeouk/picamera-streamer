import requests
import urllib.parse

# Replace with your DuckDNS information
token = ""
domains = ["", ""]  # List of domains to update (comma-separated)

def update_duckdns():
  """Updates DuckDNS record with the provided IP address."""
  global token, domains
  url = f"https://www.duckdns.org/update?verbose=true&domains={','.join(domains)}&token={token}"
  response = requests.get(url)
  if response.status_code == 200:
    lines = response.text.splitlines()
    if (lines[0] == "KO"):
        print("Error, KO was received")
    elif (lines[0] == "OK"):
        print(f"Success: {lines[3]} ({lines[1]})")
    else:
        print("Confused! Neither OK or KO was received");
  else:
    print(f"Failed to update DuckDNS: {response.text}")

def main():
  try:
    update_duckdns()
  except Exception as e:
    print(f"An error occurred: {e}")

if __name__ == "__main__":
  main()