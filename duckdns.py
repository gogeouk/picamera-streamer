import requests

# Replace with your DuckDNS information
token = "YOUR_ACCESS_TOKEN"
domains = ["YOUR_DOMAIN1", "YOUR_DOMAIN2"]  # List of domains to update (comma-separated)
ip_check_url = "http://icanhazip.com"  # URL to get your public IP

def get_public_ip():
  """Fetches your current public IP address."""
  response = requests.get(ip_check_url)
  if response.status_code == 200:
    return response.text.strip()
  else:
    raise Exception("Failed to get public IP address")

def update_duckdns(public_ip):
  """Updates DuckDNS record with the provided IP address."""
  global token, domains
  url = f"http://www.duckdns.org/update?domains={','.join(domains)}&token={token}&ip={public_ip}"
  response = requests.get(url)
  if response.status_code == 200:
    print(f"DuckDNS record updated successfully: {response.text}")
  else:
    print(f"Failed to update DuckDNS: {response.text}")

def main():
  try:
    public_ip = get_public_ip()
    update_duckdns(public_ip)
  except Exception as e:
    print(f"An error occurred: {e}")

if __name__ == "__main__":
  main()