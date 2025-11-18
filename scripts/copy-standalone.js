const fs = require('fs');
const path = require('path');

// Copy .next/standalone to functions/.next/standalone
const sourceDir = path.join(__dirname, '..', '.next', 'standalone');
const destDir = path.join(__dirname, '..', 'functions', '.next', 'standalone');

if (fs.existsSync(sourceDir)) {
  // Create destination directory
  const destParent = path.dirname(destDir);
  if (!fs.existsSync(destParent)) {
    fs.mkdirSync(destParent, { recursive: true });
  }
  
  // Copy directory recursively
  function copyRecursiveSync(src, dest) {
    const exists = fs.existsSync(src);
    const stats = exists && fs.statSync(src);
    const isDirectory = exists && stats.isDirectory();
    
    if (isDirectory) {
      if (!fs.existsSync(dest)) {
        fs.mkdirSync(dest, { recursive: true });
      }
      fs.readdirSync(src).forEach(childItemName => {
        copyRecursiveSync(
          path.join(src, childItemName),
          path.join(dest, childItemName)
        );
      });
    } else {
      fs.copyFileSync(src, dest);
    }
  }
  
  // Remove old destination if exists
  if (fs.existsSync(destDir)) {
    fs.rmSync(destDir, { recursive: true, force: true });
  }
  
  copyRecursiveSync(sourceDir, destDir);
  console.log('✓ Copied .next/standalone to functions/.next/standalone');
} else {
  console.warn('⚠ .next/standalone not found. Make sure to run "npm run build" first.');
}

