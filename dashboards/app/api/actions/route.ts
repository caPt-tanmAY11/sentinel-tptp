import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import path from 'path';

export async function POST(req: Request) {
  try {
    const { action } = await req.json();
    const basePath = path.resolve(process.cwd(), '../'); // Move to root directory HACKOHIRE/sentinel-v2-update

    let command = '';
    if (action === 'start_consumer') {
      command = `cd ${basePath} && nohup python realtime/kafka_consumer.py > /dev/null 2>&1 &`;
    } else if (action === 'start_injector') {
      command = `cd ${basePath} && nohup python data_generator/realtime_injector.py --mode stress --total 50 --tps 2 > /dev/null 2>&1 &`;
    } else if (action === 'truncate_txns') {
      // Create truncate.py if it wasn't available, but we will assume it is
      command = `cd ${basePath} && python database/truncate.py`;
    } else {
      return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
    }

    exec(command, (error, stdout, stderr) => {
      if (error) {
        console.error(`exec error: ${error}`);
      }
    });

    return NextResponse.json({ success: true, message: `${action} executed.` });
  } catch (err) {
    return NextResponse.json({ error: 'Failed to execute action' }, { status: 500 });
  }
}
