import { stopBackground } from '../launcher.ts';

export default async function stopCommand() {
  if (!stopBackground()) {
    console.log('No running TaxSentry background process was found.');
  }
}

