# Past Resolved IT Support Tickets

## Ticket: INC-2024-1847

- **Date**: 2024-11-15
- **Reporter**: Sarah Chen, Engineering Team
- **Category**: VPN
- **Priority**: P2
- **Subject**: Cannot connect to VPN after Windows update

**Description**: After the latest Windows update (KB5043076), GlobalProtect VPN client fails to connect. Shows error "PAN-GP-E4012: Connection timed out."

**Resolution**: The Windows update reset the network adapter settings. Fix:

1. Open Command Prompt as Administrator
2. Run: `netsh winsock reset`
3. Run: `netsh int ip reset`
4. Restart the computer
5. VPN connection restored after restart

**Time to resolve**: 45 minutes
**Root cause**: Windows Update KB5043076 resets Winsock catalog

---

## Ticket: INC-2024-1903

- **Date**: 2024-12-01
- **Reporter**: James Wright, Marketing Team
- **Category**: Email
- **Priority**: P3
- **Subject**: Outlook keeps asking for password repeatedly

**Description**: Every 10-15 minutes, Outlook displays a password prompt. Entering the correct password works temporarily but the prompt returns.

**Resolution**: The stored credentials were corrupted. Fix:

1. Close Outlook completely
2. Open Windows Credential Manager (Control Panel > Credential Manager)
3. Under "Windows Credentials", remove all entries containing "MicrosoftOffice" or "outlook"
4. Restart Outlook and enter credentials once
5. Check "Remember my credentials" checkbox

**Time to resolve**: 20 minutes
**Root cause**: Corrupted cached credentials in Windows Credential Manager

---

## Ticket: INC-2025-0142

- **Date**: 2025-01-20
- **Reporter**: Priya Patel, Data Science Team
- **Category**: Software Installation
- **Priority**: P3
- **Subject**: Docker Desktop not available in Software Center

**Description**: Need Docker Desktop for development work but it's not showing in Software Center.

**Resolution**: Docker Desktop requires manager approval due to licensing. Steps:

1. Manager submits approval request at https://helpdesk.acmecorp.com/software-request
2. Include business justification: "Required for containerized development and testing"
3. IT Security reviews request (usually within 24 hours)
4. Once approved, Docker Desktop appears in the user's Software Center
5. User installs from Software Center as normal

**Time to resolve**: 2 business days (approval process)
**Root cause**: Docker Desktop requires additional licensing and security approval

---

## Ticket: INC-2025-0287

- **Date**: 2025-02-10
- **Reporter**: Alex Kumar, Finance Team
- **Category**: Hardware
- **Priority**: P2
- **Subject**: Laptop screen flickering intermittently

**Description**: Dell Latitude 5540 screen flickers every few seconds. Worse when connected to external monitor via docking station. Asset tag: ACME-LT-4521.

**Resolution**: The laptop had a faulty display cable. Troubleshooting performed:

1. Updated Intel graphics driver — did not fix
2. Tested with different external monitor — external display was fine
3. Tested without docking station — flickering continued on laptop screen
4. Ran Dell hardware diagnostics (F12 > Diagnostics) — display test showed artifacts
5. Escalated to Dell warranty support — replacement display shipped
6. On-site technician replaced display cable and LCD panel

**Time to resolve**: 5 business days (including parts shipping)
**Root cause**: Faulty display cable (hardware issue, covered under warranty)

---

## Ticket: INC-2025-0356

- **Date**: 2025-03-05
- **Reporter**: Maria Santos, Customer Support Team
- **Category**: Account/Access
- **Priority**: P1
- **Subject**: Entire team locked out of CRM system

**Description**: 12 members of the Customer Support team cannot log into Salesforce CRM. Getting "Access Denied" error since 8:00 AM.

**Resolution**: A security policy change accidentally revoked the CRM access group membership. Fix:

1. Identified that the Active Directory group "CRM-Users-Support" was modified at 7:45 AM
2. The change was part of a scheduled security policy update that incorrectly targeted this group
3. Restored the group membership from backup
4. All 12 users confirmed access restored by 9:30 AM
5. Added the CRM access groups to the "protected groups" list to prevent future accidental modification

**Time to resolve**: 1.5 hours
**Root cause**: Automated security policy update incorrectly modified AD group membership

---

## Ticket: INC-2025-0401

- **Date**: 2025-03-15
- **Reporter**: Tom Richardson, Product Team
- **Category**: Network
- **Priority**: P3
- **Subject**: Cannot access internal wiki from the 5th floor conference rooms

**Description**: When connected to the Wi-Fi in 5th floor conference rooms (network: AcmeCorp-5F-Conf), cannot access wiki.acmecorp.com or any internal sites. Internet works fine.

**Resolution**: The conference room Wi-Fi was on the guest network VLAN, which doesn't have access to internal resources. Fix:

1. Verified the access point configuration for 5th floor conference rooms
2. Found that APs were configured on VLAN 50 (guest) instead of VLAN 10 (corporate)
3. Reconfigured the 3 APs in 5th floor conference rooms to VLAN 10
4. Tested connectivity — internal resources accessible
5. Updated the conference room setup documentation

**Time to resolve**: 3 hours
**Root cause**: Access points misconfigured on guest VLAN during recent network refresh
