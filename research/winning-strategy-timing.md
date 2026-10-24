# PayPal AI Hackathon: winning strategy and submission timing for Pact

Sources: the hackathon Official Rules, the main hackathon page, the Resources page, the AG Grid sponsor page (all on paypalaihackathon.devpost.com), and Devpost's own help center article on editing a submission. Where a page does not answer a question, I say so.

## 1. Timing: editing, early versus late, and the smart schedule

**A submitted entry can be edited up to the deadline.** Devpost's help center states it plainly: "You can access and make changes to your submission until the submission deadline. Once the deadline passes, you can still make changes to your project but these changes will not be reflected in your hackathon submission, only in the project within your portfolio." The Rules say the same thing from the other side (Section 5, Submission Modifications): once the Submission Period ends, no changes or alterations to the Submission are allowed, except fixes the Sponsor and Devpost permit for infringing or inappropriate material. So the judged artifact is whatever the submission contains at Nov 12, 2026, 12:00 PM Pacific Time.

**No early submission advantage is stated anywhere.** The Rules and the site pages publish no gallery opening date and no benefit for submitting early. Judging is a separate, later window: Dec 1, 2026 (2:00 PM PT) to Dec 15, 2026 (8:00 AM PT), with winners announced on or around Dec 21, 2026 (2:00 PM PT). Stage One is a pass or fail screen for theme fit and use of the featured APIs. Stage Two scores everything that passes on the five equally weighted criteria. Nothing in that structure rewards submission order. The practical risks point the other way: a last hour submission has no recovery time if an upload, a video link, or the hosted demo breaks.

**Smart schedule for a project that already works:**
1. Submit a complete, fully compliant first version several days before the deadline, as soon as the public repo, the hosted demo, and the video all exist. This locks in eligibility and proves the whole submission pipeline works.
2. Keep improving the repo, the video, and the description, and re save the submission after each improvement. Edits are free until the deadline.
3. Do the final freeze and verification pass on Nov 11 or the morning of Nov 12 PT at the latest: repo public with license visible, video public and under 3 minutes, demo URL live, credentials in the README.
4. Keep the hosted demo, the sandbox app, and the test accounts alive and free to use through Dec 15. The Rules (Section 4, Testing) require the project to stay available "until the Judging Period ends."

## 2. What the rules require, and the compliance traps

**Demo video.** The Rules say the video "should be less than three (3) minutes" and that judges are not required to watch beyond three minutes. It must be uploaded to YouTube, publicly visible, with the link on the submission form. It must show the project functioning on the device it was built for. It must not include third party trademarks or copyrighted music or other material without permission. The Presentation criterion asks whether the video shows the project working end to end and explains the problem, the audience, and why it matters. Front load the full deal loop inside the first three minutes.

**Code repository.** Public, on GitHub, Bitbucket, or GitLab. It must contain all source code, assets, and instructions needed for the project to be functional. It must include an open source license file, and the license "should be detectable and visible at the top of the repository page (in the About section)." Pact's MIT license satisfies this if the repo is public and the license file sits at the root.

**Functional demo.** A hosted demo URL, or clear and complete setup and run instructions in the repo so judges can build and run it themselves. A design mockup, static prototype, or non functional demo does not meet the requirement. The project must function as depicted in the video and the text description.

**The biggest trap for Pact: judge access to the approval step.** The Rules (Section 4, Testing) require access "free of charge and without any restriction" for testing until the Judging Period ends. If a site is private, login credentials go in the testing instructions. The Rules explicitly allow the repo README or project description to carry "test account credentials, API keys, or sandbox login details necessary to run and test the Project." Pact's flow parks at an approval step that needs the sandbox buyer and seller logins. If those credentials and step by step instructions are not in the README, a judge who runs the demo stalls at awaiting approval and the run looks broken. Put the two sandbox test account emails and passwords, plus the exact click path, in a Testing section of the README and on the submission page.

**Second trap: judges may never run the demo at all.** The Rules state that judges "are not required to test the Project and may choose to judge based solely on the text description, images, and video." The video and the written description have to carry the full story on their own, including real sandbox transaction evidence.

**Other requirements worth one line each.** The submission must identify which tools (model or AI service) were used and explain how (main page, What to Submit). PayPal integration must be central and run on the free sandbox. Stage One screens for reasonable use of the featured APIs, so the description should name the PayPal pieces plainly: Orders, Payouts, capture refunds, the Agent Toolkit, delayed disbursement as the hold model. All materials must be in English or carry an English translation.

## 3. Prize stacking math

The cap (Section 8): one Grand Prize or one Honorable Mention Prize, plus one Sponsor Prize. Every eligible submission is eligible for every Grand and Honorable prize; there is no election to make on the form. The entrant's only lever is framing and where the polish goes.

The stacks that matter for Pact:
- Ceiling: 1st Place $12,000 + Best Use of AG Grid 1st $5,000 = **$17,000**.
- Strong realistic stack A: Best Use of Agentic Commerce $5,000 + AG Grid 1st $5,000 = **$10,000**.
- Strong realistic stack B: 3rd Place $5,000 + AG Grid 2nd $2,000 = **$7,000**, or Agentic Commerce $5,000 + AG Grid 2nd $2,000 = **$7,000**.

Reasoning. The same Stage Two score drives both the Grand Prizes and the Honorable Mentions, and ties break first on Technological Implementation, then down the criteria list in order. Pact's deepest strengths are Technological Implementation (multiple PayPal products composed into one working loop, with live transaction IDs) and Innovation. Its named category fit is exact: Best Use of Agentic Commerce is an Honorable Mention, and PayPal's own Resources page uses "two agents negotiating and settling a payment between themselves (agent to agent commerce)" as the inspiration example for this hackathon. So the framing that maximizes expected value is: lead as an agentic commerce product, written to score on all five criteria for the Grand Prizes, with Best Use of Agentic Commerce as the high probability fallback at the same $5,000 as 3rd Place. There is no trade off to manage between Grand and Honorable; one framing serves both.

On the sponsor side, AG Grid is the right target and the deepest pool: $5,000 + $2,000 + three at $1,000 = $10,000 across five winners, and the rules' eligibility bar is low ("use any AG Grid tools"). One honest warning from AG Grid's own sponsor page: it says the award "covers both what your dashboard looks like and how you build it" and asks for "polish: custom widgets, theming, and layout tools, not just AG Grid or AG Charts on their own," with AG Studio and the Studio Agent Framework named. A plain AG Grid table for the audit ledger clears the rules' eligibility bar but sits below the sponsor page's stated bar for 1st Place. Expected sponsor value today is AG Grid 2nd or 3rd ($2,000 or $1,000); upgrading the ledger view toward a themed, widget based dashboard is the single change that moves the $5,000 tier into reach. The Render sponsor prizes ($1,000, $750, $500 in credits) exist and Pact already plans to host on Render, but only one sponsor prize can be won and AG Grid cash beats Render credits, so AG Grid stays the sponsor target.

## 4. Official resources a serious entrant should use

**PayPal Discord.** The Resources page opens with it: "Any questions? Connect with the PayPal and Sponsor teams on the PayPal Discord." The AG Grid page routes its questions to the same Discord. This is the stated support channel. **No office hours are listed** in the Rules, on the main page, or on the Resources page; the pages simply do not offer any.

**Webinars (recordings linked on the Resources page; all dates have passed, recordings are the value).** Oct 6, 9:00 AM PT, Start building with PayPal. Oct 7, 9:00 AM PT, Power Your PayPal Hackathon Project with APIMatic Context Plugins. Oct 12, 7:00 AM PT, Build a payments dashboard without building a dashboard (the AG Grid relevant one). Oct 13, 1:00 AM PT, Start building with PayPal.

**PayPal agent tooling docs.** The Resources page links docs.paypal.ai for the Agent Toolkit quickstart, the MCP server quickstart, and the agent tools reference, plus the PayPal AI Toolkit on GitHub and a GitHub "Getting Started with PayPal sandbox" repo. Pact already builds on the Agent Toolkit; the submission text should say so by name.

**AG Grid resources.** A free 45 day trial license, a GitHub boilerplate with AG Studio and PayPal already set up, docs on custom widgets and theming and on the Studio Agent Framework, and a recorded session, "Self serve dashboards in 30 lines of code." These are the exact materials aimed at the sponsor prize Pact targets.

**Judges (listed on the main page; the Rules note judges may change and judging may use expert panels or automated analysis).** PayPal: Jo Franchetti, Eddie Jaoude, and Marco Podien (Developer Advocates); Karthik Ravi (Software Engineer); Himraj Singh (Engineering Manager); Nathaniel Olson (Senior Product Manager). Sponsors: Sylwia Vargas (AG Grid, Senior Technical Community Manager), Ameer Hassan (APIMatic Co Founder), Mats Bryntse (Bryntum CEO), Ignacio Valdez Bicard (Channel3 Founding Engineer), Carly Richmond (Elastic), Pooja Mistry (Postman), Shifra Williams (Render). The mix is developer advocates, working engineers, and product people, which rewards a demo that shows real transactions over slideware claims.

**Bottom line.** Submit a complete version days early, edit freely until Nov 12 at noon PT, freeze on Nov 11, keep the demo and the sandbox credentials alive through Dec 15, frame for the Grand Prizes with Best Use of Agentic Commerce as the built in fallback, and spend remaining polish on the AG Grid dashboard, because that is where the sponsor money is decided.