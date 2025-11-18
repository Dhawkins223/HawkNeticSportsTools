# Firebase Deployment Guide

This guide explains how to deploy your Next.js application to Firebase Hosting with Firebase Functions.

## Prerequisites

1. **Firebase CLI installed**: Already installed as a dev dependency
2. **Firebase project**: Already configured (`hawkneticsportstools`)
3. **Node.js 20+**: Required for Firebase Functions (you may need to upgrade from Node 18)

## Initial Setup

1. **Login to Firebase** (if not already logged in):
   ```bash
   npx firebase login
   ```

2. **Verify Firebase project**:
   ```bash
   npx firebase use --add
   ```
   Select `hawkneticsportstools` when prompted.

## Building for Production

Before deploying, you need to build your Next.js application and prepare Firebase Functions:

```bash
npm run firebase:build
```

This command will:
1. Build your Next.js application (`npm run build`)
2. Copy the standalone output to the functions directory
3. Install function dependencies

Alternatively, you can do it step by step:

```bash
# Build Next.js
npm run build

# Copy standalone output to functions
npm run firebase:copy-standalone

# Install function dependencies
cd functions
npm install
cd ..
```

## Deployment

### Deploy Everything (Hosting + Functions)

```bash
npm run firebase:deploy
```

Or:

```bash
npx firebase deploy
```

### Deploy Only Hosting

```bash
npm run firebase:deploy:hosting
```

### Deploy Only Functions

```bash
npm run firebase:deploy:functions
```

## Environment Variables

For Firebase Functions, you'll need to set environment variables:

```bash
npx firebase functions:config:set nba.api.key="YOUR_API_KEY"
npx firebase functions:config:set admin.token="YOUR_ADMIN_TOKEN"
# Add other environment variables as needed
```

Or use the newer approach with `.env` files (recommended for Firebase Functions v2):

1. Create a `.env` file in the `functions` directory
2. Add your environment variables there
3. Firebase Functions v2 will automatically load them

## Database Setup

Since you're using Prisma with SQLite, you'll need to:

1. **For Production**: Consider migrating to a cloud database (PostgreSQL, MySQL, etc.)
2. **For Development**: The SQLite database won't work in Firebase Functions (read-only filesystem)

### Recommended: Migrate to Cloud SQL or Supabase

Update your `prisma/schema.prisma` to use a PostgreSQL database:

```prisma
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}
```

Then update your connection string in Firebase Functions environment variables.

## Important Notes

1. **Node.js Version**: Firebase Functions require Node.js 20. Make sure your local environment matches.

2. **Database**: SQLite won't work in Firebase Functions. You'll need to migrate to a cloud database.

3. **File System**: Firebase Functions have a read-only filesystem except for `/tmp`. Make sure your app doesn't try to write files.

4. **Cold Starts**: Firebase Functions may have cold starts. Consider using Cloud Run for better performance.

5. **API Routes**: All API routes will be handled by the Firebase Function.

## Troubleshooting

### Build Errors

If you encounter build errors:
- Make sure all dependencies are installed
- Check that Node.js version is 20+
- Verify `next.config.js` is correct

### Deployment Errors

- Check Firebase project ID matches `.firebaserc`
- Verify you're logged in: `npx firebase login`
- Check function logs: `npx firebase functions:log`

### Runtime Errors

- Check function logs in Firebase Console
- Verify environment variables are set correctly
- Ensure database connection is configured

## Next Steps

1. Set up a production database (PostgreSQL recommended)
2. Configure environment variables in Firebase
3. Test the deployment in a staging environment
4. Set up CI/CD for automatic deployments

