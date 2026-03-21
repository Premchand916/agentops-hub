# IT Troubleshooting Runbook

## VPN Connection Issues

### Problem: Unable to connect to company VPN

**Error Code: VPN-E4012**

Symptoms:

- VPN client shows "Connection Timed Out"
- Unable to access internal resources
- Error code E-4012 in VPN client logs

Resolution Steps:

1. Verify your internet connection is working (try opening google.com)
2. Restart the VPN client application completely (not just disconnect/reconnect)
3. Check that your VPN credentials haven't expired — credentials expire every 90 days
4. If using GlobalProtect VPN, ensure you're connecting to `vpn.acmecorp.com` (not the old `vpn-legacy.acmecorp.com`)
5. Clear VPN cache: Go to Settings > Advanced > Clear Cache in the VPN client
6. If still failing, check the VPN service status at https://status.acmecorp.com
7. Last resort: Uninstall and reinstall the VPN client from the Software Center

**Escalation**: If none of the above works, create a Priority 2 ticket to the Network Team with the error logs attached.

---

### Problem: VPN connected but slow performance

**Error Code: VPN-P3001**

Symptoms:

- VPN connects successfully but applications are slow
- File transfers take excessively long
- Video calls drop or freeze

Resolution Steps:

1. Run a speed test while connected to VPN: visit https://speedtest.acmecorp.com
2. If speed is below 10 Mbps, try switching VPN regions:
   - US East: `vpn-east.acmecorp.com`
   - US West: `vpn-west.acmecorp.com`
   - Europe: `vpn-eu.acmecorp.com`
   - Asia: `vpn-asia.acmecorp.com`
3. Disable split tunneling if enabled (Settings > Network > Split Tunnel > Off)
4. Close bandwidth-heavy applications (streaming, large downloads)
5. If on Wi-Fi, try connecting via ethernet cable

**Escalation**: If speed remains below 5 Mbps after trying all regions, escalate to Network Team as Priority 3.

---

## Email Issues

### Problem: Unable to send or receive emails

**Error Code: MAIL-E2001**

Symptoms:

- Outlook shows "Disconnected" or "Trying to connect"
- Emails stuck in Outbox
- New emails not appearing

Resolution Steps:

1. Check Microsoft 365 service status at https://status.office.com
2. Restart Outlook completely (File > Exit, not just close)
3. Check your mailbox size: File > Account Settings > Account Settings > Double-click account > More Settings > Advanced. Mailbox limit is 50 GB.
4. Clear Outlook cache: Close Outlook, delete files in `%localappdata%\Microsoft\Outlook\RoamCache`
5. Remove and re-add your email account in Outlook
6. Try accessing email via https://outlook.office.com to determine if it's a client or server issue

**Escalation**: If web access also fails, escalate to Email Team as Priority 2.

---

## Software Installation

### How to install software from the Software Center

All approved software is available through the AcmeCorp Software Center.

Steps:

1. Open the Start Menu and search for "Software Center"
2. Browse or search for the application you need
3. Click "Install" — no admin password required for approved software
4. Installation typically takes 5-15 minutes
5. If the software is not in the Software Center, submit a Software Request at https://helpdesk.acmecorp.com/software-request

**Common software available:**

- Visual Studio Code (latest version)
- Python 3.13 (with pip)
- Docker Desktop (requires manager approval)
- Slack Desktop
- Zoom
- Adobe Acrobat Reader

**Software NOT available in Software Center (requires special request):**

- Database management tools (DBeaver, pgAdmin) — request via IT Security
- Network monitoring tools — requires Network Team approval
- Custom development tools — discuss with your team lead first

---

## Password & Account Issues

### How to reset your password

Your AcmeCorp password expires every 90 days. You'll receive email reminders at 14 days, 7 days, and 1 day before expiration.

**Self-service password reset:**

1. Go to https://password.acmecorp.com
2. Verify your identity using your registered phone number or email
3. Choose a new password meeting these requirements:
   - Minimum 12 characters
   - At least one uppercase letter
   - At least one number
   - At least one special character
   - Cannot be any of your last 10 passwords
4. Your new password syncs across all systems within 15 minutes

**If you're locked out:**

1. After 5 failed login attempts, your account locks for 30 minutes
2. If you can't wait, call the IT Helpdesk at ext. 5555 (available 24/7)
3. Have your employee ID ready for identity verification

**Multi-Factor Authentication (MFA):**

- MFA is required for all employees since January 2025
- Use the Microsoft Authenticator app on your phone
- If you lose your phone, contact IT Helpdesk for a temporary bypass code
- Temporary bypass codes expire after 24 hours

---

## Hardware Issues

### Laptop not turning on

Resolution Steps:

1. Ensure the laptop is charged — connect the power adapter and wait 5 minutes
2. Perform a hard reset: Hold the power button for 15 seconds, then press it again
3. Remove all external devices (monitors, USB drives, docking station)
4. If using a docking station, try connecting the power adapter directly to the laptop
5. Check if the power adapter LED is lit — if not, the adapter may be faulty

**Escalation**: If the laptop still won't turn on, create a Hardware ticket. Include the laptop asset tag (sticker on the bottom of the laptop).

### Requesting new equipment

All hardware requests go through your manager for approval:

1. Go to https://helpdesk.acmecorp.com/hardware-request
2. Select the equipment type (laptop, monitor, keyboard, mouse, headset)
3. Provide business justification
4. Your manager will receive an approval request via email
5. Once approved, equipment typically arrives within 5-7 business days
6. Standard equipment refresh cycle is every 3 years
