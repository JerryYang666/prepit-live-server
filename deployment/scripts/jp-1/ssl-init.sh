#!/bin/bash

if ! [ -x "$(command -v docker compose)" ]; then
  echo 'Error: docker compose is not installed.' >&2
  exit 1
fi

domains=(edge-jp-tokyo-1.prepit-ai.com)
rsa_key_size=4096
data_path="./files/certbot"
email="$SSL_EMAIL" # Adding a valid address is strongly recommended
staging=0 # Set to 1 if you're testing your setup to avoid hitting request limits

# show domains
echo "### Domains: ${domains[@]}"

# Check for existing certificates and filter out domains that already have valid certs
echo "### Checking for existing certificates..."
filtered_domains=()
for domain in "${domains[@]}"; do
  if [ -d "$data_path/conf/live/$domain" ]; then
    echo "Certificate for $domain already exists, skipping..."
  else
    filtered_domains+=("$domain")
    echo "Certificate for $domain needs to be obtained..."
  fi
done

# show filtered domains
echo "### Filtered Domains: ${filtered_domains[@]}"

# Replace the original domains array with our filtered one
domains=("${filtered_domains[@]}")

# Check if we still have domains to process
if [ ${#domains[@]} -eq 0 ]; then
  echo "All domains already have certificates. Nothing to do."
  exit 0
fi

# Create dummy certificates for each domain
for domain in "${domains[@]}"; do
  echo "### Creating dummy certificate for $domain ..."
  path="/etc/letsencrypt/live/$domain"
  mkdir -p "$data_path/conf/live/$domain"
  docker compose run --rm --entrypoint "\
    openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1\
      -keyout '$path/privkey.pem' \
      -out '$path/fullchain.pem' \
      -subj '/CN=localhost'" certbot
  echo
done


echo "### Starting nginx ..."
docker compose up --force-recreate -d nginx
echo

# Delete dummy certificates for each domain
for domain in "${domains[@]}"; do
  echo "### Deleting dummy certificate for $domain ..."
  docker compose run --rm --entrypoint "\
    rm -Rf /etc/letsencrypt/live/$domain && \
    rm -Rf /etc/letsencrypt/archive/$domain && \
    rm -Rf /etc/letsencrypt/renewal/$domain.conf" certbot
  echo
done


echo "### Requesting Let's Encrypt certificate for $domains ..."
# Instead of combining all domains for a single request, we request them one by one
for domain in "${domains[@]}"; do
  echo "### Requesting Let's Encrypt certificate for $domain..."
  
  # Select appropriate email arg
  case "$email" in
    "") email_arg="--register-unsafely-without-email" ;;
    *) email_arg="--email $email" ;;
  esac

  # Enable staging mode if needed
  if [ $staging != "0" ]; then staging_arg="--staging"; fi

  docker compose run --rm --entrypoint "\
    certbot certonly --webroot -w /var/www/certbot \
      $staging_arg \
      $email_arg \
      -d $domain \
      --rsa-key-size $rsa_key_size \
      --agree-tos \
      --force-renewal" certbot
  echo
done

echo "### Reloading nginx ..."
docker compose exec nginx nginx -s reload

echo "### Starting certbot renew ..."
docker compose up -d certbot
echo