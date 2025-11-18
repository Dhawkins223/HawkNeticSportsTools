// Import the functions you need from the SDKs you need
import { initializeApp, getApps, FirebaseApp } from "firebase/app";
import { getAnalytics, Analytics } from "firebase/analytics";

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyBR8F73HD-w1ZfXuexgj04cirejgV8DW5I",
  authDomain: "hawkneticsportstools.firebaseapp.com",
  projectId: "hawkneticsportstools",
  storageBucket: "hawkneticsportstools.firebasestorage.app",
  messagingSenderId: "24499156062",
  appId: "1:24499156062:web:e5e0490141a9ac1e71f0cf",
  measurementId: "G-XS9HØRS1JB"
};

// Initialize Firebase
let app: FirebaseApp;
let analytics: Analytics | null = null;

if (typeof window !== "undefined") {
  // Only initialize on client side
  if (getApps().length === 0) {
    app = initializeApp(firebaseConfig);
    analytics = getAnalytics(app);
  } else {
    app = getApps()[0];
  }
} else {
  // Server-side: just initialize the app without analytics
  if (getApps().length === 0) {
    app = initializeApp(firebaseConfig);
  } else {
    app = getApps()[0];
  }
}

export { app, analytics };

