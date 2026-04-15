# AutoDialer Ultimate - Configuration Guide

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| FREEPBX_IP | FreePBX server IP | Required |
| EXTENSION_PASSWORD | SIP extension password | Required |
| DOMAIN_NAME | Domain for HTTPS | - |
| DB_PASSWORD | PostgreSQL password | Auto-generated |
| JWT_SECRET | JWT signing secret | Auto-generated |
| AMI_PASSWORD | Asterisk AMI password | Auto-generated |
| MAX_CALLS | Maximum concurrent calls | 50 |
| DEFAULT_CPS | Default calls per second | 5 |
| TTS_VOICE | TTS voice (denis/irina) | denis |

## FreePBX Setup (Server-1)

1. Create SIP extension 291
2. Set password
3. Enable outbound calls
4. Create outbound route

## Scaling

### Increasing concurrent calls

1. Edit `/opt/autodialer/config/.env`
2. Set `MAX_CALLS=100`
3. Restart: `systemctl restart autodialer`

### Multiple dialer nodes

Use Redis and PostgreSQL on separate servers.
