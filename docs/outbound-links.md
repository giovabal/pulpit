# Outbound links

*Where do the channels send their readers?*

A movement that lives on Telegram still depends on the open web: donation pages, merchandise shops, video hosting, mirrors on mainstream platforms, its own sites. `--links` (Outputs → *Outbound links*) reads the web links of the observed channels' messages and reports who links where, by category.

---

## What counts as a link

A message can link out in four places, all read:

- URLs written in its text (`http(s)://…` and `www.…`);
- **hidden links** — link text whose URL is not in the text — and auto-linked bare domains (`example.com` written without a scheme), captured by the crawler from Telegram's message entities (`Message.link_urls`);
- its inline **URL buttons** (also in `link_urls`);
- its **link preview** (`Message.webpage_url`).

Messages crawled before `link_urls` existed have only their text and preview until **Refresh message stats** (`--refresh-messages-stats`) backfills the field. It does so only while Telegram still serves the text stored at first crawl, so a ban stub never writes links.

Every URL is reduced to its **site**:

- host lower-cased, port dropped, an internationalised name written as punycode, a leading `www.`, `m.`, `mobile.` or `amp.` stripped;
- the **registered domain**: the last two labels, three under a common second-level suffix (`news.example.co.uk` → `example.co.uk`);
- except on **hosting platforms** — `*.substack.com`, `*.blogspot.com`, `*.wordpress.com`, `*.myshopify.com`, `*.bigcartel.com`, `*.carrd.co`, `*.github.io`, … — where each subdomain is somebody's own outlet and stays a site of its own, and a few **service hosts** (`docs.google.com`, `drive.google.com`, …) whose subdomain names a different service;
- Telegram's own hosts (`t.me`, `telegram.me`, `telegra.ph`, …) are left out: a t.me link is a citation, already in the graph.

A site counts **once per message**, however often the message repeats it. Shortened links (`bit.ly`, `t.co`, …) are not resolved, which would take a network request per link; shorteners are a category of their own.

## Categories — Manage → Domains

The analyst files sites under **domain categories** in *Manage → Domains*. A starter list ships with Pulpit:

- Mainstream social, Video, Alternative platform, Messaging;
- Crowdfunding / donations, Shop / merch;
- Blog / newsletter, Archive, File hosting, Shortener.

Everything else starts *uncategorised*. A movement's own shop or a party's site is the analyst's call. Categories can be renamed, recoloured, added or deleted. Three **roles** drive the share measures: *Monetisation* (by default crowdfunding and shops), *Mainstream platform* (mainstream social and video) and *Alternative platform*.

The site list there is the **domain index**: every site the in-target channels link to inside their in-target periods, with the messages and channels linking to it and the first and last link. Rebuild it with `python manage.py index_domains`, the crawl option **Index → Index link domains** (`crawl_channels --index-domains`), or *Rebuild index* on the page. A new outlet on a hosting platform starts in its platform's category (a new `name.substack.com` goes under Blog / newsletter). A site no message links to any more keeps its category and note.

## What the layer reports

Over the observed channels of the export's graph (dead leaves excluded), inside their in-target periods and the date window, and per timeline period:

**Per channel** — node measures, in the channel table's *Links* group, the map's size-by menu, CSV, XLSX and GEXF/GraphML:

| Column | Definition |
| :-- | :-- |
| Linking posts share | messages carrying at least one outbound link / messages |
| Distinct sites | sites linked to |
| Platform diversity | Hill number of order 2 over the categories of the channel's *categorised* links: 1/Σp², the effective number of equally used categories (Hill 1973; Jost 2006); empty when none is categorised |
| Monetisation / Mainstream / Alternative link share | links to sites whose category has that role / all the channel's links |

The three shares count uncategorised links in the denominator, so they are **lower bounds** while sites stay uncategorised. The *Categorised* column of `links.html` says how much of each channel's linking is covered.

**Per site** — messages, channels, first and last link, and the labels linking to it most.

**Label × category matrix** — for every partition label group (e.g. Nation): the link events of each label's channels by category, as counts or as row shares. *Who relies on which infrastructure.*

**Co-linking pairs** — two channels linking to more of the same sites than their activity and the sites' popularity explain. The channel × site links are compared with the **bipartite configuration model** (BiCM; Saracco et al. 2015, 2017): the maximum-entropy ensemble of random channel × site graphs in which every channel links, on average, to as many sites as it does and every site is linked by as many channels as it is. Under it, a pair's number of shared sites is a sum of independent site-by-site coin flips (probability p₁ₛ · p₂ₛ for site *s*), so its p-value is the exact Poisson-binomial tail (on very large networks, the Poisson approximation with the same mean; `colinking.p_method` records which). The p-values are Benjamini–Hochberg-corrected over **every** pair of linking channels, and q < 0.05 is validated. Pairs sharing at least 2 sites are listed, most significant first, with the expected number of shared sites and the shared sites themselves (rarest first). A validated pair across labels points to infrastructure shared beyond what activity explains — a common shop, a common donation page, the same local news sites.

*Why not a simpler null?* The hypergeometric test of statistically validated networks (Tumminello et al. 2011) draws each channel's sites uniformly from the sites in scope. On link data that is badly wrong: a handful of sites — a video platform, a mainstream network, a donation service, a movement shop — are linked by most channels, so any two active channels share them, and the uniform null validates them for it. On the Active Club corpus (207 linking channels, 793 sites) it validated 3,305 of 21,321 pairs; the configuration model, which knows those sites are popular, validates 3.

## Reading it

- **A link is a pointer the channel published**, not a visit, a payment or an affiliation. A channel linking to a mainstream news site may be quoting it to mock it.
- **Few validated pairs is a finding, not a failure.** When channels' overlaps are explained by how much each links and how popular the sites are, the test says so. Sort by p to see the strongest overlaps even when the correction over thousands of pairs leaves few below q < 0.05, and read the shared sites listed with each pair.
- **Categories are the analyst's.** Every share depends on the filing. The export records the categories as they stood when it ran (`data/links.json` carries their names, colours and roles).
- **Coverage.** Messages crawled before hidden links were captured carry their text URLs and preview only, until a stats refresh backfills them.

## Outputs

- `data/links.json` (and `data_<period>/links.json` on a timeline export): summary, categories, per-channel rows with every site linked, sites, matrices, co-linking pairs.
- `links.html` (with `--html`): the category bar and table, the label × category matrix, the channel, site and pair tables, with a period navigator.
- `links.xlsx` (with `--xlsx`): `Channels`, `Sites` (one sheet per period too), `Categories`, `Co-linking`, one `Matrix <group>` sheet per label group.
- `channel_sites.csv` (long format: channel, site, category, messages) and `links_colinking.csv` (with `--csv`).

The fixed rules — the site rule, the platform and Telegram hosts, the co-linking null, its convergence and exact-tail budget, the validation level and listing floor, the diversity index — are listed in each export's `PARAMETERS.md`.

## References

- Hill, M.O. (1973) "Diversity and evenness: a unifying notation and its consequences." *Ecology* 54(2):427–432. [doi:10.2307/1934352](https://doi.org/10.2307/1934352)
- Jost, L. (2006) "Entropy and diversity." *Oikos* 113(2):363–375. [doi:10.1111/j.2006.0030-1299.14714.x](https://doi.org/10.1111/j.2006.0030-1299.14714.x)
- Saracco, F., Di Clemente, R., Gabrielli, A. & Squartini, T. (2015) "Randomizing bipartite networks: the case of the World Trade Web." *Scientific Reports* 5:10595. [doi:10.1038/srep10595](https://doi.org/10.1038/srep10595)
- Saracco, F., Straka, M.J., Di Clemente, R., Gabrielli, A., Caldarelli, G. & Squartini, T. (2017) "Inferring monopartite projections of bipartite networks: an entropy-based approach." *New Journal of Physics* 19(5):053022. [doi:10.1088/1367-2630/aa6b38](https://doi.org/10.1088/1367-2630/aa6b38)
- Tumminello, M., Miccichè, S., Lillo, F., Piilo, J. & Mantegna, R.N. (2011) "Statistically validated networks in bipartite complex systems." *PLoS ONE* 6(3):e17994. [doi:10.1371/journal.pone.0017994](https://doi.org/10.1371/journal.pone.0017994) — the uniform-draw null not used here.

---

← [Image copies](image-copies.md) · [Workflow](workflow.md) →
