# Pilot recruitment message (DRAFT — awaiting owner review)

**Status: DRAFT. Do not send this to anyone yet.** Owner decision D3
([OWNER_DECISIONS.md](../OWNER_DECISIONS.md)) authorizes one pilot round only
after the owner reviews this recruitment kit, the donation flow is rehearsed,
and the notice is the ratified version. Scope is 10–30 donors from the
owner's personal network with **no public recruitment**; the stop conditions
in [HUMAN_REVIEW.md](../HUMAN_REVIEW.md) and
[DATA_COLLECTION.md](../DATA_COLLECTION.md) apply. This message is a template,
not a sent message: no recruitment has happened and no donors exist yet.

The draft below is written for a personal message (chat or SMS) to someone the
owner knows. It is deliberately plain and does not promise anything.

---

## Draft message

> Hi! I've been building a small SMS spam-filtering tool that runs locally on
> my own computer, and I'm looking for a few people to help me test the part
> where donated messages get reviewed and labeled by hand. Nothing is
> automated and nothing is public.
>
> If you're willing, you would submit one or a few real text messages you
> received — spam you got, or a normal message — through a private form that
> only works on my computer. Submitting is optional and you can say no without
> any effect on anything. The tool works fine whether or not you donate.
>
> Before you decide, please read the privacy notice (version `2026-11-01-v4`)
> shown on the donation page at `/privacy-notice`, or ask me and I'll walk you
> through it. The short version:
>
> - The form stores only the message text you paste, an optional label you
>   think fits (spam or not), the language, and your consent choices. It never
>   asks for your name, phone number, email, contacts, or sender numbers.
> - The message is kept for **90 days** from when you consent, then deleted;
>   my backups get deleted on the same schedule.
> - Right after you submit, the page shows a random **withdrawal ID**. Your
>   browser does not save it, so keep it somewhere private if you might want
>   to withdraw later. Withdrawing (using that ID and the erase button on the
>   page) immediately erases the message, the label, and the language; only a
>   content-free marker with the notice version and timestamps remains until
>   its expiry. If you withdraw later, contact me about backups or anything
>   already derived from it.
>
> Please **never submit** any of these, even by accident:
>
> - a **live OTP** or one-time code (yours or anyone's)
> - **passwords** or **PINs**
> - **account credentials** (bank, e-wallet, email, or any login details)
> - **someone else's private conversation** — only messages sent directly to
>   you, or ones you wrote yourself
> - **full sender details** (complete sender numbers or contact information)
>
> The page also runs an automatic screen for likely personal details, codes,
> and links, but it can miss things, so please check and remove anything
> private from the text yourself before submitting.
>
> If you're interested, I'll send you the form link and the notice, and you
> can take your time deciding. And if you'd rather not, that's completely
> fine — thanks for reading this far!

---

## Before sending — owner checklist

- [ ] Owner has reviewed and approved this recruitment kit (D3 condition).
- [ ] The donation flow has been rehearsed end to end (D3 condition).
- [ ] The donation page serves notice version `2026-11-01-v4` (ratified in D2)
      and the `/privacy-notice` page matches `docs/privacy-notice.md`.
- [ ] Recipients are personal-network contacts only; the message is never
      posted publicly or forwarded to strangers.
- [ ] Donor count stays within the D3 scope of 10–30.
- [ ] HUMAN_REVIEW and DATA_COLLECTION stop conditions have been re-read on
      the day of sending, and any stop condition that fires halts collection.
- [ ] Consent records, the restricted consent register, and 90-day retention
      purging are working as the notice describes.


## Filipino/English review addendum — draft, not authorized to send

The retry-key disclosure on the local form and privacy notice has changed.
The owner and qualified privacy reviewer must review and ratify the revised
disclosure before enabling any real pilot. Prior D2 approval is not approval
of the new wording.

Suggested comprehension prompt (native-speaker review required): "Kung hindi
tiyak kung natanggap ang mensahe, huwag awtomatikong ipadala ulit. Maaari mong
subukang muli ang parehong form sa pahinang ito, o magtanong sa operator."
Ask the participant to explain what happens if a receipt is lost, what the
withdrawal ID is for, and whether a donation is required to use the detector.
Record only a pseudonymous session code, language, actual comprehension
results and copy revisions. No participant responses have been collected.
