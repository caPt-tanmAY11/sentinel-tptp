import nodemailer from 'nodemailer';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const envPath = path.join(__dirname, '..', 'HACKOHIRE', 'sentinel-v2-update', 'dashboards', '.env.local');
const envContent = fs.readFileSync(envPath, 'utf8');
const passMatch = envContent.match(/^EMAIL_PASS=(.*)/m);
const pass = passMatch && passMatch[1] ? passMatch[1].trim() : '';

console.log("Extracted PASS length:", pass.length);

if (!pass) {
    console.error("No EMAIL_PASS found in .env.local");
    process.exit(1);
}

const transporter = nodemailer.createTransport({
    service: 'gmail',
    auth: {
        user: 'tanmay06lko@gmail.com',
        pass: pass
    }
});

transporter.verify(function(error, success) {
  if (error) {
    console.error("Transporter Verification Error:", error);
  } else {
    console.log("Server is ready to take our messages");
    
    transporter.sendMail({
      from: 'tanmay06lko@gmail.com',
      to: 'tanmay.vishwakarma24@spit.ac.in',
      subject: 'Test connection',
      text: 'Testing nodemailer connection, please ignore.'
    }).then(info => console.log('Mail sent successfully:', info.response))
      .catch(err => console.error('Error sending mail:', err));
  }
});
