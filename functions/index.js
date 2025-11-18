const { onRequest } = require('firebase-functions/v2/https');
const { setGlobalOptions } = require('firebase-functions/v2');
const path = require('path');
const fs = require('fs');

// Set global options for all functions
setGlobalOptions({
  maxInstances: 10,
});

// For standalone output, we use the Next.js standalone server
// The .next/standalone directory should be in functions/.next/standalone
let server;
let isServerReady = false;

async function getServer() {
  if (isServerReady && server) {
    return server;
  }

  try {
    // Try to use standalone server (production)
    // In Firebase Functions, the standalone directory should be in the functions folder
    const standalonePath = path.join(__dirname, '.next', 'standalone');
    const serverPath = path.join(standalonePath, 'server.js');
    
    // Check if standalone server exists
    if (fs.existsSync(serverPath)) {
      // Change to standalone directory so relative paths work
      const originalCwd = process.cwd();
      process.chdir(standalonePath);
      
      // Load the standalone server
      server = require(serverPath);
      isServerReady = true;
      
      // Restore original directory
      process.chdir(originalCwd);
      
      console.log('Using Next.js standalone server');
      return server;
    }
  } catch (error) {
    console.warn('Standalone server not found, using Next.js directly:', error.message);
  }

  // Fallback: use Next.js directly (for development or if standalone fails)
  try {
    const next = require('next');
    const app = next({ 
      dev: false,
      conf: { 
        distDir: path.join(__dirname, '..', '.next'),
      },
      dir: path.join(__dirname, '..'),
    });
    
    await app.prepare();
    server = app.getRequestHandler();
    isServerReady = true;
    console.log('Using Next.js request handler');
    return server;
  } catch (error) {
    console.error('Failed to initialize Next.js:', error);
    throw error;
  }
}

exports.nextjsServer = onRequest(
  {
    memory: '1GiB',
    timeoutSeconds: 60,
  },
  async (req, res) => {
    try {
      const handler = await getServer();
      
      if (typeof handler === 'function') {
        // Next.js request handler
        return handler(req, res);
      } else {
        // Standalone server (Express app) - handle as Express request
        return handler(req, res);
      }
    } catch (error) {
      console.error('Error handling request:', error);
      res.status(500).send('Internal Server Error');
    }
  }
);
