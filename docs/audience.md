# Audience

*Who reads these channels? Telegram shows a channel's subscribers only to its admins, so a crawler sees one number per channel and no people. The part of the audience that can be followed person by person is the **commenters**: the accounts replying in a channel's discussion group. The Audience page measures them — how concentrated the commenting is, how far commenters spread across channels and labels, which channels share them, and whether they come back.*

Open it from **Audience** in the top menu (`/audience/`). It needs comments in the database: run the crawl with **Fetch replies** (`crawl_channels --fetch-replies`) on channels that have a discussion group. The page reads the database directly, and every section has a **CSV** of its main table (as in every CSV Pulpit writes, a channel title that a spreadsheet would run as a formula comes behind an apostrophe). Every `structural_analysis` export carries the same sections too — see [In an export](#in-an-export).

---

## What is counted

- **Channels**: the in-target channels, or those under one container label when the **Scope** menu is set (as on the home page).
- **Posts**: their alive posts dated inside their in-target periods — the same rule the graph uses.
- **Commenters**: the *user accounts* replying to those posts. A channel or group posting as itself is not a commenter (it has its own section, below). Telegram bots and *bulk posters* — accounts with 100 or more replies under one post, such as an archive dumped into a thread — are left out; [Manage → Commenters](web-interface.md#commenters--managecommenters) lists every account and lets you override either flag.

The **Scope** menu limits the page to one label's channels, as on the home page ([Web interface](web-interface.md)). The page states how many channels in scope have comments. On most corpora that is a minority, so the figures describe those channels' commenters, **not the audience of the whole network**. Commenters are also a self-selected minority of any audience: most members of an online community never post (the "1% rule", tested by van Mierlo 2014), and the most active are not typical of the rest (Kim et al. 2021). The pages show aggregates only; no account is named.

---

## Participation

How unevenly the replies are spread over the accounts writing them. A comment section can look like a crowd while a few regulars write most of it: on the Facebook pages of German parties, a small set of *hyperactive* users wrote a large part of the comments and set what the discussion was about (Papakyriakopoulos et al. 2019, 2020).

| Figure | Definition |
| :-- | :-- |
| **Most active 10% / 1%** | Share of the replies written by the ⌈p·n⌉ most active accounts |
| **Gini coefficient** | Of replies per account, with the small-sample correction n/(n−1) (Deltas 2003), so a channel with few commenters does not look more equal than it is. The **Lorenz curve** is the same distribution drawn |
| **Effective commenters** | 1 / Σ sᵢ², sᵢ each account's share of the replies — the effective number of parties of Laakso & Taagepera (1979): the replies are as concentrated as if that many accounts wrote equal shares |
| **One-time commenters** | Accounts with a single reply, and the share of replies they wrote |
| **Hyperactive accounts** | Outliers of the activity distribution by the skewness-adjusted boxplot of Hubert & Vandervieren (2008): more replies than Q3 + 1.5·e^(3·MC)·IQR, MC the medcouple, a robust measure of skewness (Brys, Hubert & Struyf 2004). This is the rule Papakyriakopoulos et al. (2019) use; it adapts to the skew instead of assuming a normal distribution, which reply counts never follow |

The **By channel** table gives the same figures per channel. The top-10% share, Gini and effective commenters need at least 20 commenters. *Hyperactive* there is the share of the channel's replies written by the hyperactive accounts, whose activity is measured across the whole scope. *Per 100 subs.* divides the commenters of the whole period by today's subscribers, and commenters need not subscribe: read it as a rough rate.

---

## Breadth

Over how many channels, and across how many labels, each commenter spreads. With plenty of channels to choose from, people keep to a few sources — Schmidt et al. (2017) found it in the news consumption of 376 million Facebook users. Raw counts mislead in two ways, and both are corrected:

- **Activity.** An account with 300 replies reaches more channels by chance alone. Each account is set against its **rarefaction** expectation (Hurlbert 1971): the distinct channels expected if its n replies were drawn without replacement from all the replies in scope, E[Sₙ] = Σᵢ [1 − C(N − Nᵢ, n) / C(N, n)], Nᵢ the replies on channel i and N their total. One-reply accounts are left out: one reply reaches one channel.
- **Count vs spread.** 99 replies on German channels and 1 on an Italian one are not "2 nations". Per partition label group, an account's spread is its **effective number of labels** — the Hill number of order 1, exp(−Σ sₗ ln sₗ) (Hill 1973) — and its **cross-label share**, the replies outside its main label.

Labels are read at each post's date; a container group (such as continents) through its child labels. A label group is reported only when its labels cover at least half the replies in scope.

---

## Audience overlap

Which channels share commenters beyond chance — the audience-duplication networks political communication research uses to tell a fragmented public from a shared one (Webster & Ksiazek 2012; Mukerjee, Majó-Vázquez & González-Bailón 2018).

**The test.** Two big channels share many commenters anyway. Each pair's shared commenters are compared with a null that keeps **every commenter's number of channels exactly** and every channel's number of commenters on average: each commenter's set of k channels is drawn with probability proportional to the product of the channels' weights — maximum-entropy sampling of a fixed size (Chen, Dempster & Liu 1994) — with the weights fitted to the channels' commenters. A pair's shared commenters are then a sum of binomials, one per commenter degree, so the p-value is exact; q is Benjamini–Hochberg over every pair, and a pair is marked at q < 0.05.

The bipartite configuration model (Saracco et al. 2015) is the usual null for such projections, but it fixes the commenters' degrees only on average: a one-channel commenter can sit on two channels in the null. When most commenters use a single channel, that inflates every expected overlap. Keeping the commenter side exact is the commenter half of the fixed-degree-sequence model (Neal 2014).

**What the page shows.**

- The channel × channel **matrix** of shared commenters, tinted by the ratio to the expectation (more or fewer than chance) and marked where significant; pairs with fewer than 3 commenters shared and expected stay untinted.
- **Exclusive**: the share of a channel's commenters who comment on no other channel in scope, beside the share the null expects.
- The **pairs**, most significant first, and the same test **between labels** of each partition group: do the commenters of one nation's channels also comment on another's?
- **Audience follows citations**: Pearson's r between log(1 + shared commenters) and log(1 + forwards and mentions, either way) over the channel pairs, with a QAP p-value from 9,999 permutations of the citation matrix's channels (Krackhardt 1987, 1988). It asks whether the audience network follows the citation network.

---

## Retention

Whether the comment audience renews itself or rests on a core that ages (the lifecycle reading of Danescu-Niculescu-Mizil et al. 2013).

- **Commenters per month**: accounts active each month and accounts commenting for the first time. Both follow the comment coverage too — the CSV adds the channels with comments each month.
- **Cohorts**: accounts grouped by the quarter of their first reply, and the share of each cohort replying again 1 to 8 quarters later. A quarter not yet over at the data's end is left blank.

A reply's date is its own; replies stored without one take their post's.

---

## Channels as commenters

A reply's sender can be a channel instead of a person: an admin posting under the channel's name. Telegram marks such senders with a negative id, which tells three cases apart: a channel answering under **its own posts**, a **discussion group's anonymous admins**, and a channel commenting on **another channel's posts**.

The last is a channel-to-channel tie the citation network does not see, since that is built from forwards and mentions. The table lists each pair with its comments and dates, and *Also cited* says whether the two channels forward or mention each other, either way, in any stored message (when the commenting channel has not been crawled, only the other channel's messages can show it). Channels are public actors, so they are named.

Every channel commenting on another channel's posts gets a row in the channels list, even when it has since been deleted, so the table links it. See [Workflow § Channels found in comments](workflow.md#channels-found-in-comments).

---

## In an export

`structural_analysis` writes the five sections into the export unless told not to (Outputs → *Audience*, CLI `--no-audience`): `audience.html` with **HTML**, `audience.xlsx` with **XLSX**, the sections' CSVs (`audience_<section>.csv`) with **CSV**, and `data/audience.json` always. Same statistics as the page, on the export's own scope:

- **Channels**: the graph's observed in-target channels, so the export's channel types, scope filter and lost / private switches apply. Dead leaves and environment channels are left out, as everywhere the page says *in target*.
- **Posts**: inside the channels' in-target periods and the export's **Start** / **End** dates.
- **Timeline**: with a timeline (`--timeline-step`), each period is computed again on its own channels and days, and the page gets a period navigator; a period without comments is left out of it. The workbook's *Summary*, per-channel participation and overlap pairs then carry a *Period* column (*All periods*, then each period). A period's retention only sees that period's replies, so its cohorts are short.
- **Commenters**: the bot and bulk-poster flags and the Manage → Commenters overrides as they stand when the export runs.

With no reply in scope the section is skipped with a warning. `PARAMETERS.md` lists the thresholds, null-model settings and seeds the sections ran with. See [Export formats](export-formats.md#audiencehtml--audiencexlsx--audience_csv--the-commenters).

---

## References

- Benjamini, Y. & Hochberg, Y. (1995) "Controlling the false discovery rate." *Journal of the Royal Statistical Society B* 57(1):289–300.
- Brys, G., Hubert, M. & Struyf, A. (2004) "A robust measure of skewness." *Journal of Computational and Graphical Statistics* 13(4):996–1017.
- Chen, X.-H., Dempster, A.P. & Liu, J.S. (1994) "Weighted finite population sampling to maximize entropy." *Biometrika* 81(3):457–469.
- Danescu-Niculescu-Mizil, C., West, R., Jurafsky, D., Leskovec, J. & Potts, C. (2013) "No country for old members: user lifecycle and linguistic change in online communities." *WWW 2013*.
- Deltas, G. (2003) "The small-sample bias of the Gini coefficient." *Review of Economics and Statistics* 85(1):226–234.
- Hill, M.O. (1973) "Diversity and evenness: a unifying notation and its consequences." *Ecology* 54(2):427–432.
- Hubert, M. & Vandervieren, E. (2008) "An adjusted boxplot for skewed distributions." *Computational Statistics & Data Analysis* 52(12):5186–5201.
- Hurlbert, S.H. (1971) "The nonconcept of species diversity." *Ecology* 52(4):577–586.
- Kim, J.W., Guess, A., Nyhan, B. & Reifler, J. (2021) "The distorting prism of social media." *Journal of Communication* 71(6):922–946.
- Krackhardt, D. (1987) "QAP partialling as a test of spuriousness." *Social Networks* 9(2):171–186; (1988) "Predicting with networks." *Social Networks* 10(4):359–381.
- Laakso, M. & Taagepera, R. (1979) "'Effective' number of parties." *Comparative Political Studies* 12(1):3–27.
- Mukerjee, S., Majó-Vázquez, S. & González-Bailón, S. (2018) "Networks of audience overlap in the consumption of digital news." *Journal of Communication* 68(1):26–50.
- Neal, Z. (2014) "The backbone of bipartite projections." *Social Networks* 39:84–97.
- Papakyriakopoulos, O., Shahrezaye, M., Medina Serrano, J.C. & Hegelich, S. (2019) "Distorting political communication: the effect of hyperactive users in online social networks." *IEEE INFOCOM Workshops*.
- Papakyriakopoulos, O., Medina Serrano, J.C. & Hegelich, S. (2020) "Political communication on social media: a tale of hyperactive users and bias in recommender systems." *Online Social Networks and Media* 15:100058.
- Saracco, F., Di Clemente, R., Gabrielli, A. & Squartini, T. (2015) "Randomizing bipartite networks: the case of the World Trade Web." *Scientific Reports* 5:10595.
- Schmidt, A.L. et al. (2017) "Anatomy of news consumption on Facebook." *PNAS* 114(12):3035–3039.
- van Mierlo, T. (2014) "The 1% rule in four digital health social networks." *Journal of Medical Internet Research* 16(2):e33.
- Webster, J.G. & Ksiazek, T.B. (2012) "The dynamics of audience fragmentation." *Journal of Communication* 62(1):39–56.

---

← [Outbound links](outbound-links.md) · [Web interface](web-interface.md) →
