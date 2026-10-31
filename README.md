# brianpiotrowski.com

The Offer Letter by Brian Piotrowski — blog + Candidate Spotlight podcast.
Hosted free on GitHub Pages.

## Writing a new post

1. Open the `_posts` folder and click **Add file → Create new file**.
2. Name it `YYYY-MM-DD-short-title.md`, for example `2026-11-04-hiring-in-2027.md`.
3. Paste this at the top, then write the post below it:

   ```
   ---
   title: "Hiring in 2027"
   description: "One or two sentences shown in the post list and on LinkedIn."
   image: "/assets/images/blog/hiring-in-2027.jpg"   # optional
   ---
   ```

4. Click **Commit changes**. The site updates in about two minutes.

To add an image, upload it to `assets/images/blog/` and reference it with
`![description](/assets/images/blog/your-image.jpg)`.

## Scheduling a post

Give the post a future date and time in its file name and front matter:

```
_posts/2026-11-04-hiring-in-2027.md
---
title: "Hiring in 2027"
date: 2026-11-04 10:00:00 -0600
---
```

Use `-0600` from November to mid-March (standard time) and `-0500` from
mid-March to early November (daylight time). The site rebuilds every
Wednesday just after 10am Central, and the post goes live then. Posts
dated on other days go live at the next morning's daily build.

Note: the repository is public, so a scheduled post can be read on GitHub
before it goes live on the site.

## Podcast

Nothing to do. Publish in Riverside as usual; the site reads the Riverside feed
every day and on every change, and adds new episodes automatically.

## Settings

Everything you'd want to change (newsletter username, podcast links, email) is
at the top of `_config.yml`.

## How it's built

- `scripts/import_godaddy.py` — one-time import of the 69 posts from GoDaddy.
- `scripts/fetch_podcast.py` — pulls episodes from Riverside before each build.
- `.github/workflows/deploy.yml` — builds and publishes the site.
