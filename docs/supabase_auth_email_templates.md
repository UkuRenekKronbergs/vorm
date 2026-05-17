# Supabase Auth emailid eesti keeles

Hosted Supabase projektis ei tule kinnitus- ja paroolitaastuse emailid
rakenduse koodist, vaid Supabase Authi seadetest.

Seadista nii:

1. Ava Supabase Dashboard.
2. Mine `Authentication` -> `Email Templates`.
3. Ava vastav template.
4. Pane `Subject` ja `Body` alloleva malli järgi.
5. Salvesta ja saada testmail.

Supabase templated kasutavad Go template muutujaid. Vorm.ai signup lisab uutele
kasutajatele `user_metadata.language = "et"`, seega saab sama template'i hiljem
laiendada mitmekeelseks tingimusega `{{ if eq .Data.language "et" }}`. Praegu on
kogu rakendus eesti keeles, nii et allolevad mallid on vaikimisi eestikeelsed.

## Confirm signup

Subject:

```text
Kinnita oma Vorm.ai konto
```

Body:

```html
<h2>Kinnita oma Vorm.ai konto</h2>

<p>Tere!</p>

<p>
  Vajuta allolevale nupule, et kinnitada oma email ja lõpetada konto loomine.
</p>

<p>
  <a
    href="{{ .ConfirmationURL }}"
    style="display:inline-block;padding:12px 18px;background:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;"
  >
    Kinnita email
  </a>
</p>

<p>
  Kui nupp ei avane, kopeeri see link brauserisse:<br>
  <a href="{{ .ConfirmationURL }}">{{ .ConfirmationURL }}</a>
</p>

<p>
  Kui sina seda kontot ei loonud, võid selle kirja rahulikult ignoreerida.
</p>

<p>Vorm.ai</p>
```

## Reset password

Subject:

```text
Taasta Vorm.ai parool
```

Body:

```html
<h2>Taasta Vorm.ai parool</h2>

<p>Tere!</p>

<p>
  Saime taotluse sinu Vorm.ai konto parooli taastamiseks.
  Vajuta allolevale nupule ja määra rakenduses uus parool.
</p>

<p>
  <a
    href="{{ .ConfirmationURL }}"
    style="display:inline-block;padding:12px 18px;background:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;"
  >
    Määra uus parool
  </a>
</p>

<p>
  Kui nupp ei avane, kopeeri see link brauserisse:<br>
  <a href="{{ .ConfirmationURL }}">{{ .ConfirmationURL }}</a>
</p>

<p>
  Kui sina parooli taastamist ei küsinud, võid selle kirja ignoreerida.
  Sinu praegune parool jääb kehtima.
</p>

<p>Vorm.ai</p>
```

## Magic link

Subject:

```text
Sinu Vorm.ai sisselogimislink
```

Body:

```html
<h2>Sinu Vorm.ai sisselogimislink</h2>

<p>Tere!</p>

<p>Vajuta allolevale nupule, et Vorm.ai-sse sisse logida.</p>

<p>
  <a
    href="{{ .ConfirmationURL }}"
    style="display:inline-block;padding:12px 18px;background:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;"
  >
    Logi sisse
  </a>
</p>

<p>
  Kui nupp ei avane, kopeeri see link brauserisse:<br>
  <a href="{{ .ConfirmationURL }}">{{ .ConfirmationURL }}</a>
</p>

<p>Vorm.ai</p>
```

## Invite user

Subject:

```text
Sind kutsuti Vorm.ai-sse
```

Body:

```html
<h2>Sind kutsuti Vorm.ai-sse</h2>

<p>Tere!</p>

<p>
  Sind kutsuti kasutama Vorm.ai rakendust. Konto loomiseks ja kutse
  vastuvõtmiseks vajuta allolevale nupule.
</p>

<p>
  <a
    href="{{ .ConfirmationURL }}"
    style="display:inline-block;padding:12px 18px;background:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;"
  >
    Võta kutse vastu
  </a>
</p>

<p>
  Kui nupp ei avane, kopeeri see link brauserisse:<br>
  <a href="{{ .ConfirmationURL }}">{{ .ConfirmationURL }}</a>
</p>

<p>Vorm.ai</p>
```

## Confirm email change

Subject:

```text
Kinnita Vorm.ai emaili muutmine
```

Body:

```html
<h2>Kinnita emaili muutmine</h2>

<p>Tere!</p>

<p>
  Vajuta allolevale nupule, et kinnitada Vorm.ai konto uus emailiaadress:
  {{ .NewEmail }}.
</p>

<p>
  <a
    href="{{ .ConfirmationURL }}"
    style="display:inline-block;padding:12px 18px;background:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;"
  >
    Kinnita uus email
  </a>
</p>

<p>
  Kui sina seda muudatust ei teinud, ära vajuta lingile.
</p>

<p>Vorm.ai</p>
```

## Reauthentication

Subject:

```text
Kinnita Vorm.ai tegevus
```

Body:

```html
<h2>Kinnita tegevus</h2>

<p>Tere!</p>

<p>Sinu kinnituskood on:</p>

<p style="font-size:24px;font-weight:700;letter-spacing:4px;">{{ .Token }}</p>

<p>Kui sina seda tegevust ei alustanud, võid selle kirja ignoreerida.</p>

<p>Vorm.ai</p>
```

## Management API payload

Sama asja saab teha ka Supabase Management API-ga. Pane keskkonda
`SUPABASE_ACCESS_TOKEN` ja `PROJECT_REF`, siis kasuta payloadi failist
[`supabase_auth_email_templates.json`](supabase_auth_email_templates.json).

```powershell
$headers = @{
  Authorization = "Bearer $env:SUPABASE_ACCESS_TOKEN"
  "Content-Type" = "application/json"
}
$body = Get-Content docs/supabase_auth_email_templates.json -Raw
Invoke-RestMethod `
  -Method Patch `
  -Uri "https://api.supabase.com/v1/projects/$env:PROJECT_REF/config/auth" `
  -Headers $headers `
  -Body $body
```

Tootmise jaoks tasub Supabase Authile seadistada ka custom SMTP
(`Authentication` -> `Settings` -> `SMTP Settings`), sest Supabase vaikimisi
emailiserver on mõeldud eelkõige arenduseks ja demoks.
