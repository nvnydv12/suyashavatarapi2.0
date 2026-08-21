# Free Fire Profile Image API

Changes in this build:
- guild/clan title moved further right
- guild/clan placeholder box characters now render as Apple logo
- improved Apple logo rendering in nickname/guild text
- Apple-symbol nicknames stay larger instead of shrinking too much
- all previous fixes preserved

## Local run

Install dependencies directly in your system Python:

```powershell
py -m pip install -r requirements.txt
```

Start the API:

```powershell
py app.py
```

API endpoint:

```text
http://127.0.0.1:5000/profile-image?uid=6950878222&key=suyash
```

The response is a PNG image. Replace the UID to generate another profile card.

## Vercel deployment

### Dashboard method

1. Push this folder to a GitHub repository.
2. Open [vercel.com](https://vercel.com), choose **Add New > Project**, and import the repository.
3. Keep the framework as **Other**; `vercel.json` already configures Python.
4. In **Project Settings > Environment Variables**, add:

	```text
	API_KEY=suyash
	INFO_API_URL=https://info.bhuwanhex.bond/info
	```

5. Deploy, then use the deployed URL:

	```text
	https://YOUR-PROJECT.vercel.app/profile-image?uid=6950878222&key=suyash
	```

If an old `API_KEY=PANKAJ` variable already exists in Vercel, update it to `suyash` before redeploying.

### Vercel CLI method

Install and log in once:

```powershell
py -m pip install vercel
vercel login
```

From this project folder, deploy:

```powershell
vercel
```

For production deployment:

```powershell
vercel --prod
```

Add the same `API_KEY` and `INFO_API_URL` values when Vercel asks for environment variables, or add them later in the dashboard and redeploy.
