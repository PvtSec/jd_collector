#!/usr/bin/env python3
"""Seed the dataset with additional tech companies not in the original 201.

Emits raw entries (shape matching data/raw/agent*.json) to data/raw/seed_external.json,
which scripts/consolidate.py picks up on its next run. Each curated company emits TWO
raw entries (website/careers and website/jobs); consolidate dedups by normalized name
and merges the URLs into career_page_url + alternate_career_urls, so the resolver
(scripts/resolve_ats.py) can try both when detecting the real ATS.

Discovery approach (honest):
  Dynamic scraping of YC (ycombinator.com/companies), Built In (builtin.com/companies)
  and Wellfound (wellfound.com/company_list) was probed live (2026-07):
    - YC:       Inertia app; the company directory is client-rendered via XHR with no
                extractable anchor cards and no JSON data island -> not scrapable via
                static HTTP or a light Playwright pass.
    - Built In: client-rendered Next.js; the company list is loaded via XHR to an
                internal api.builtin.com endpoint (POST, auth-gated) -> not scrapable.
    - Wellfound: 403 bot-blocked.
  So the reliable seed is a CURATED list of real tech companies (security / QA / dev-
  tools / AI / India-tech) known to hire for the candidate's target roles and likely to
  use a standard ATS. The resolver validates the real ATS for each. Re-runnable: dedups
  against the existing companies.json by normalized name, so only NEW companies are
  added.

Read-only: no network calls (the curated list is static). The resolver does the fetches.
"""
import json, os, re

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT = os.path.join(DATA, "raw", "seed_external.json")

# Curated seed: (company_name, website, domain_hint). Focused on the candidate's target
# domains (Penetration Tester / QA Automation / SDET) and remote/India/EU/APAC hiring.
# career URLs are derived as {website}/careers and {website}/jobs; the resolver validates.
CURATED = [
    # --- Application/product security ---
    ("Snyk", "https://snyk.io", "appsec/SAST"),
    ("Wiz", "https://www.wiz.io", "cloud security"),
    ("Orca Security", "https://orca.security", "cloud security"),
    ("Aqua Security", "https://www.aquasec.com", "cloud/container security"),
    ("CrowdStrike", "https://www.crowdstrike.com", "EDR/security"),
    ("SentinelOne", "https://www.sentinelone.com", "EDR/security"),
    ("Abnormal Security", "https://abnormalsecurity.com", "email security"),
    ("Semgrep", "https://semgrep.dev", "SAST/code scanning"),
    ("Checkmarx", "https://checkmarx.com", "SAST"),
    ("Veracode", "https://www.veracode.com", "SAST"),
    ("SonarSource", "https://www.sonarsource.com", "code quality/SAST"),
    ("GitGuardian", "https://www.gitguardian.com", "secrets detection"),
    ("Legit Security", "https://www.legitsecurity.com", "ASPM"),
    ("Chainguard", "https://www.chainguard.dev", "supply-chain security"),
    ("Tailscale", "https://tailscale.com", "zero-trust networking"),
    ("1Password", "https://1password.com", "secrets/password mgmt"),
    ("Bitwarden", "https://bitwarden.com", "password mgmt"),
    ("Fleet", "https://fleetdm.com", "device security/MDM"),
    ("Axonius", "https://www.axonius.com", "cyber asset mgmt"),
    ("HackerOne", "https://www.hackerone.com", "pentest/bug bounty"),
    ("Bugcrowd", "https://www.bugcrowd.com", "pentest/bug bounty"),
    ("Intigriti", "https://www.intigriti.com", "pentest/bug bounty"),
    ("YesWeHack", "https://www.yeswehack.com", "pentest/bug bounty"),
    ("Cobalt", "https://www.cobalt.io", "pentest as a service"),
    ("Synack", "https://www.synack.com", "pentest as a service"),
    ("Pentera", "https://pentera.io", "automated pentest"),
    ("Rapid7", "https://www.rapid7.com", "security/vuln mgmt"),
    ("Tenable", "https://www.tenable.com", "vuln mgmt"),
    ("GreyMatter", "https://greymatter.com", "security"),
    ("Saviynt", "https://www.saviynt.com", "IAM"),
    ("Coro", "https://www.coro.net", "SMB security"),
    ("Knotable", "https://www.knotable.com", "security"),
    ("Datadog", "https://www.datadog.com", "observability/security"),
    ("Sentry", "https://sentry.io", "observability"),
    # --- QA / test automation ---
    ("BrowserStack", "https://www.browserstack.com", "test platform (India)"),
    ("LambdaTest", "https://www.lambdatest.com", "test platform (India)"),
    ("Sauce Labs", "https://saucelabs.com", "test platform"),
    ("Mabl", "https://www.mabl.com", "low-code test automation"),
    ("Testim", "https://www.testim.io", "test automation"),
    ("Tricentis", "https://www.tricentis.com", "test automation"),
    ("Qase", "https://qase.io", "test management"),
    ("TestRail", "https://www.testrail.com", "test management"),
    ("Xray", "https://www.getxray.app", "test management"),
    ("Perfecto", "https://www.perfecto.io", "test platform"),
    ("Bitrise", "https://bitrise.io", "mobile CI/testing"),
    ("Codemagic", "https://codemagic.io", "mobile CI/testing"),
    ("CircleCI", "https://circleci.com", "CI/CD"),
    ("Buildkite", "https://buildkite.com", "CI/CD"),
    ("QASource", "https://www.qasource.com", "QA services (India)"),
    ("ImpactQA", "https://www.impactqa.com", "QA services (India)"),
    ("TestingXperts", "https://www.testingxperts.com", "QA services (India)"),
    # --- Dev tools / AI (remote-friendly) ---
    ("Supabase", "https://supabase.com", "BaaS"),
    ("PostHog", "https://posthog.com", "product analytics"),
    ("Linear", "https://linear.app", "issue tracking"),
    ("Coder", "https://coder.com", "cloud dev env"),
    ("Modal", "https://modal.com", "serverless GPU"),
    ("Replicate", "https://replicate.com", "AI model hosting"),
    ("Together AI", "https://www.together.ai", "AI infra"),
    ("Anyscale", "https://www.anyscale.com", "distributed compute"),
    ("Vercel", "https://vercel.com", "frontend platform"),
    ("Hasura", "https://hasura.io", "GraphQL (India)"),
    ("Postman", "https://www.postman.com", "API platform (India)"),
    ("GitHub", "https://github.com", "dev platform"),
    ("Atlassian", "https://www.atlassian.com", "dev collab"),
    ("Grafana Labs", "https://grafana.com", "observability"),
    ("HashiCorp", "https://www.hashicorp.com", "infra tooling"),
    # --- India-tech (QA/security/dev, remote or India offices) ---
    ("Razorpay", "https://razorpay.com", "fintech (India)"),
    ("PhonePe", "https://www.phonepe.com", "fintech (India)"),
    ("Cashfree", "https://www.cashfree.com", "fintech (India)"),
    ("Zerodha", "https://zerodha.com", "fintech (India)"),
    ("Groww", "https://groww.in", "fintech (India)"),
    ("Cred", "https://cred.club", "fintech (India)"),
    ("ShareChat", "https://sharechat.com", "social (India)"),
    ("Meesho", "https://www.meesho.com", "ecommerce (India)"),
    ("Innovaccer", "https://innovaccer.com", "healthtech (India)"),
    ("Zeta", "https://www.zeta.tech", "fintech (India)"),
    ("Swiggy", "https://www.swiggy.com", "foodtech (India)"),
    ("Zomato", "https://www.zomato.com", "foodtech (India)"),
    # --- Remote-first staffing/platforms (QA/security talent) ---
    ("Turing", "https://www.turing.com", "remote talent"),
    ("Andela", "https://andela.com", "remote talent"),
    ("Toptal", "https://www.toptal.com", "remote talent"),
    ("BairesDev", "https://www.bairesdev.com", "remote dev services"),
    # --- More security (small-to-large) ---
    ("Trellix", "https://www.trellix.com", "XDR/security"),
    ("Qualys", "https://www.qualys.com", "vuln mgmt"),
    ("Fortinet", "https://www.fortinet.com", "network security"),
    ("Palo Alto Networks", "https://www.paloaltonetworks.com", "network security"),
    ("Zscaler", "https://www.zscaler.com", "cloud security"),
    ("Netskope", "https://www.netskope.com", "CASB/SSE"),
    ("Lookout", "https://www.lookout.com", "mobile security"),
    ("Auth0", "https://auth0.com", "IAM"),
    ("Okta", "https://www.okta.com", "IAM"),
    ("CyberArk", "https://www.cyberark.com", "PAM"),
    ("BeyondTrust", "https://www.beyondtrust.com", "PAM"),
    ("Delinea", "https://delinea.com", "PAM/secrets"),
    ("Thales", "https://www.thalesgroup.com", "security/crypto"),
    ("Entrust", "https://www.entrust.com", "IAM/pki"),
    ("Varonis", "https://www.varonis.com", "data security"),
    ("Forcepoint", "https://www.forcepoint.com", "DLP/SSE"),
    ("Proofpoint", "https://www.proofpoint.com", "email security"),
    ("Abnormal Security", "https://abnormalsecurity.com", "email security"),
    ("Noname Security", "https://nonamesecurity.com", "API security"),
    ("Salt Security", "https://salt.security", "API security"),
    ("Wallarm", "https://www.wallarm.com", "API security"),
    ("Escape", "https://escape.tech", "API security"),
    ("Datadog", "https://www.datadog.com", "observability"),
    ("Sentry", "https://sentry.io", "observability"),
    ("Snyk", "https://snyk.io", "appsec"),
    ("Cymulate", "https://cymulate.com", "BAS"),
    ("Pentera", "https://pentera.io", "automated pentest"),
    ("Mandiant", "https://www.mandiant.com", "IR/threat intel"),
    ("Recorded Future", "https://www.recordedfuture.com", "threat intel"),
    ("Censys", "https://censys.io", "attack surface"),
    ("Shodan", "https://www.shodan.io", "attack surface"),
    ("Cobalt", "https://www.cobalt.io", "pentest as a service"),
    ("Synack", "https://www.synack.com", "pentest as a service"),
    ("Network Intelligence", "https://www.niiconsulting.com", "security services (India)"),
    ("ISOAH", "https://www.isoah.com", "security services (India)"),
    ("KratosLabs", "https://kratoslabs.com", "security (India)"),
    ("Smokescreen", "https://www.smokescreen.com", "deception security (India)"),
    ("Lucideus", "https://www.lucideus.com", "security (India)"),
    ("WiJungle", "https://www.wijungle.com", "UTM/security (India)"),
    ("Seclore", "https://www.seclore.com", "data security (India)"),
    ("Infisecure", "https://www.infisecure.com", "bot/security (India)"),
    # --- More QA / test (small-to-large) ---
    ("Katalon", "https://www.katalon.com", "test automation"),
    ("Testim", "https://www.testim.io", "test automation"),
    ("Reflect", "https://reflect.run", "test automation"),
    ("BugBug", "https://bugbug.io", "test automation"),
    ("Endtest", "https://endtest.io", "test automation"),
    ("TestSigma", "https://testsigma.com", "test automation"),
    ("Kobiton", "https://kobiton.com", "mobile testing"),
    ("Headspin", "https://www.headspin.io", "mobile testing"),
    ("Apptim", "https://apptim.com", "mobile testing"),
    ("Rainforest QA", "https://www.rainforestqa.com", "QA as a service"),
    ("Test IO", "https://www.test.io", "crowdtesting"),
    ("uTest", "https://www.utest.com", "crowdtesting"),
    ("Applause", "https://www.applause.com", "crowdtesting"),
    ("Global App Testing", "https://www.globalapptesting.com", "crowdtesting"),
    ("Digitify", "https://www.digitify.com", "QA/digital (India)"),
    # --- More dev tools / AI / infra (remote-friendly, small-to-large) ---
    ("Render", "https://render.com", "cloud platform"),
    ("Fly.io", "https://fly.io", "edge hosting"),
    ("Railway", "https://railway.app", "cloud platform"),
    ("Northflank", "https://northflank.com", "PaaS"),
    ("Porter", "https://porterrun.com", "PaaS"),
    ("SST", "https://sst.io", "serverless framework"),
    ("Temporal", "https://temporal.io", "workflow engine"),
    ("Convex", "https://convex.dev", "BaaS"),
    ("Xata", "https://xata.io", "serverless DB"),
    ("Neon", "https://neon.tech", "serverless postgres"),
    ("Turso", "https://turso.tech", "edge DB"),
    ("Upstash", "https://upstash.com", "serverless redis"),
    ("Tinybird", "https://www.tinybird.co", "real-time data"),
    ("Hex", "https://hex.tech", "data notebooks"),
    ("MotherDuck", "https://motherduck.com", "duckdb cloud"),
    ("Pulumi", "https://www.pulumi.com", "IaC"),
    ("Spacelift", "https://spacelift.io", "IaC automation"),
    ("env0", "https://www.env0.com", "IaC automation"),
    ("Ottertune", "https://ottertune.com", "DB tuning"),
    ("Fermyon", "https://www.fermyon.com", "wasm/cloud"),
    ("Estuary", "https://estuary.dev", "data streaming"),
    ("Deci", "https://deci.ai", "AI infra"),
    ("Tabnine", "https://www.tabnine.com", "AI code assist"),
    ("Codium", "https://www.codium.ai", "AI test/code"),
    ("Qodo", "https://www.qodo.ai", "AI code quality"),
    ("Snyk", "https://snyk.io", "appsec"),
    ("Aikido", "https://www.aikido.dev", "ASPM"),
    ("Cycode", "https://cycode.com", "code security"),
    ("ArmorCode", "https://armorcode.com", "ASPM"),
    ("Kondukto", "https://kondukto.io", "ASPM"),
    # --- More India-tech (remote / India offices) ---
    ("Zoho", "https://www.zoho.com", "SaaS (India)"),
    ("Freshworks", "https://www.freshworks.com", "SaaS (India)"),
    ("Chargebee", "https://www.chargebee.com", "subscription billing (India)"),
    ("Kissflow", "https://kissflow.com", "workflow SaaS (India)"),
    ("Mad Street Den", "https://madstreetden.com", "AI (India)"),
    ("Uniphore", "https://www.uniphore.com", "AI (India)"),
    ("Aryaka", "https://www.aryaka.com", "network (India/US)"),
    ("Druva", "https://www.druva.com", "data protection (India)"),
    ("Postman", "https://www.postman.com", "API platform (India)"),
    ("BrowserStack", "https://www.browserstack.com", "test platform (India)"),
    ("Mphasis", "https://www.mphasis.com", "IT services (India)"),
    ("LTIMindtree", "https://www.ltimindtree.com", "IT services (India)"),
    ("Hexaware", "https://www.hexaware.com", "IT services (India)"),
    ("Cybage", "https://www.cybage.com", "IT services (India)"),
    ("Persistent", "https://www.persistent.com", "IT services (India)"),
    ("Calsoft", "https://www.calsoft.com", "IT services (India)"),
    ("TCS", "https://www.tcs.com", "IT services MNC (India)"),
    ("Infosys", "https://www.infosys.com", "IT services MNC (India)"),
    ("Wipro", "https://www.wipro.com", "IT services MNC (India)"),
    ("HCLTech", "https://www.hcltech.com", "IT services MNC (India)"),
    ("Tech Mahindra", "https://www.techmahindra.com", "IT services MNC (India)"),
]


def _norm(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)


def main():
    comps = json.load(open(os.path.join(DATA, "companies.json")))
    existing = {_norm(c["company_name"]) for c in comps}

    # preserve any prior non-curated entries in seed_external.json (none expected)
    out_entries = []
    if os.path.exists(OUT):
        for e in json.load(open(OUT)):
            if e.get("source_platform") != "curated":
                out_entries.append(e)

    added = 0
    skipped = 0
    for name, website, hint in CURATED:
        if _norm(name) in existing:
            skipped += 1
            continue
        # emit /careers and /jobs variants; consolidate merges both per company
        for path in ("/careers", "/jobs"):
            out_entries.append({
                "company_name": name,
                "career_page_url": website.rstrip("/") + path,
                "website": website,
                "domain_hint": hint,
                "ats_type": "unknown",
                "source_platform": "curated",
            })
        added += 1

    with open(OUT, "w") as f:
        json.dump(out_entries, f, indent=2, ensure_ascii=False)
    print(f"Curated seed: {added} new companies emitted ({skipped} already in dataset) "
          f"-> {OUT}")
    print(f"  {len(out_entries)} raw entries total (2 per company).")
    print("Next: run scripts/resolve_ats.py to detect their ATS, then scripts/consolidate.py.")


if __name__ == "__main__":
    main()