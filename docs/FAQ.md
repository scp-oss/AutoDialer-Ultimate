# AutoDialer Ultimate - FAQ

## Q: SIP registration fails?

A: Check:
- FreePBX IP is correct
- Extension 291 exists
- Password matches
- Network connectivity

## Q: Calls not connecting?

A: Verify:
- `asterisk -rx "pjsip show registrations"`
- Firewall allows SIP/RTP
- Outbound route exists in FreePBX

## Q: No audio or DTMF?

A: Check RTP ports 10000-20000 are open.

## Q: High CPU usage?

A: Reduce MAX_CALLS or CPS settings.

## Q: How to backup?

A: Backup PostgreSQL and `/opt/autodialer/config/.env`
