# Lemonade Store

`lemonade-store` is the full offline business suite that sits above
Lemonade Cashier.

The goal is a ma-and-pa retail operating system that runs locally on a
Strix Halo workstation, keeps the owner out of repetitive admin work, and
does not require paid SaaS services to keep the shop moving.

Tie Dye Farms is the first business target. Lemonade Cashier proves the
system in a tiny shop first. Soil sales can then roll into the same suite as
the next inventory category and, later, as a larger soil warehouse workflow.

## Product Shape

```text
lemonade-store
  ->
lemonade-cashier
  checkout, cash, barter records, CIT, receipts, inventory events
  ->
lemonade-inventory
  product intake, stock counts, soil/vape/convenience SKU tracking
  ->
lemonade-accounting
  ledgers, expenses, tax summaries, cash reconciliation
  ->
lemonade-marketeer
  product posts, organic campaigns, website content, promotion calendar
  ->
lemonade-supplier
  purchase orders, supplier comparison, reorder suggestions
  ->
lemonade-reports
  owner summaries, end-of-day close, weekly business snapshots
```

Each repo is a department in the store. Each department has:

- a responsibility
- local data it owns
- agents that can perform that department's work
- permissions for what each agent can propose or mutate
- an audit trail for anything business-critical

The cashier remains the source of truth for store events. Marketing and
accounting consume audited cashier and inventory events. They do not invent
sales.

## Operating Model

The suite should be able to run offline inside the shop:

- local SQLite and JSONL data first
- local Lemonade-powered agents when useful
- no paid cloud dependency for daily operation
- exports for accountant, owner, bank, or tax filing
- owner approval before public-facing actions

Cloud services can publish public material, protect a website, or receive
explicit exports. They should not be required to complete a sale, close a
till, reconcile CIT, or understand the current inventory state.

## Departments

### Lemonade Cashier

Responsibilities:

- cash-only checkout
- barter records when explicitly approved
- cart, totals, cash tender, change
- receipts
- CIT drops, pickups, bags, handoff, reconciliation
- audit and replay

Non-responsibilities:

- paid ads
- accounting reports beyond source events
- card, wallet, or processor-backed payment as a core feature

### Lemonade Accounting

Responsibilities:

- daily cash close
- cash drawer reconciliation
- CIT reconciliation
- barter ledger
- sales by category
- soil sales tracking
- expenses and supplier costs
- simple tax summaries
- CSV export for outside accountants
- daily and weekly owner reports

The accounting agent should read cashier, inventory, and supplier events. It
should not mutate cashier transactions after the fact.

### Lemonade Marketeer

Responsibilities:

- organic social media drafting
- product post generation from inventory data
- campaign calendars
- website content updates
- product photo reuse from the capture pipeline
- local promotion suggestions
- posting checklist and audit trail

The first rule is no required ad spend. Paid ads may be an optional future
integration, but the default path is organic marketing the shop can run
without spending money.

The marketer agent can draft public posts, product pages, and campaigns. It
must not publish without owner approval unless a future policy explicitly
grants that permission.

### Lemonade Inventory

Responsibilities:

- product onboarding
- category definitions
- SKU aliases
- stock counts
- soil, vape, convenience, and retail categories
- zone and shelf metadata
- reorder thresholds

Inventory should feed both cashier recognition and marketing content.

### Lemonade Supplier

Responsibilities:

- supplier catalog records
- purchase order drafts
- supplier price comparison
- reorder suggestions
- received inventory checks

### Lemonade Reports

Responsibilities:

- end-of-day summaries
- weekly owner digest
- slow movers
- category revenue
- cash and CIT exceptions
- inventory risk
- marketing activity summaries

## Website Package

Each store should have a simple website package that can be launched with
step-by-step instructions. The default public website should be static,
cheap to operate, and easy to edit from store data.

Recommended website pieces:

- home page
- product/category pages
- soil availability page
- store hours and location
- contact form or contact instructions
- organic promotion landing pages
- privacy and local-data statement
- owner-approved social links

The website is public. The store system is local. Public pages should receive
only approved product, promotion, and business information.

## Cloudflare Website Setup

Use Cloudflare Pages for the public website. Cloudflare's Pages docs describe
connecting a GitHub or GitLab repository for deployments, and Cloudflare's
custom domain docs require the custom domain to be on the same Cloudflare
account as the Pages project. Turnstile can protect forms without showing a
traditional CAPTCHA.

Sources:

- [Cloudflare Pages](https://pages.cloudflare.com/)
- [Cloudflare Pages custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/)
- [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/)

Step-by-step launch path:

1. Create a Cloudflare account for the business.
2. Add the store domain to Cloudflare DNS.
3. Create a website repository, for example `tiedye-farms-site`.
4. Keep the website static for the first version.
5. Add pages for home, products, soil, hours, contact, and policies.
6. In Cloudflare, open **Workers & Pages**.
7. Create a new Pages project.
8. Connect the GitHub repository.
9. Choose the production branch, usually `main`.
10. Configure the build command and output directory for the chosen static
    site generator.
11. Deploy the first build.
12. Add the custom domain in the Pages project.
13. Confirm DNS records in Cloudflare.
14. Enable HTTPS.
15. Add Turnstile to any contact or request form.
16. Document the exact edit-and-publish steps for the owner.

Owner workflow:

```text
inventory update
  ->
marketer agent drafts website/social copy
  ->
owner approves
  ->
website repo updates
  ->
Cloudflare Pages deploys
```

The marketer agent can prepare website changes. Publishing still needs an
approval boundary until the owner explicitly configures trusted automation.

## First Milestones

1. Finish Lemonade Cashier core and keep it green.
2. Define the shared `lemonade-store` event vocabulary.
3. Add accounting exports from cashier events.
4. Draft the first Tie Dye Farms static website.
5. Add organic post drafts from inventory records.
6. Add soil as a tracked category in inventory and reports.

## Design Rule

Make the owner's work disappear only after the system can explain what it did.

Every agent action should answer:

- what department requested this?
- what source data did it use?
- what did it change?
- who approved it?
- how can it be replayed or exported?
