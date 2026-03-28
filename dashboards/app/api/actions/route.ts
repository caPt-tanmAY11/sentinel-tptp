import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import util from 'util';
import path from 'path';

const execPromise = util.promisify(exec);

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
      command = `cd ${basePath} && python database/truncate.py`;
    } else if (action === 'monitor') {
      command = `cd ${basePath} && python run_pipeline.py --step monitor`;
      await execPromise(command);
      return NextResponse.json({ success: true, message: `Pipeline step 'monitor' completed` });
    } else {
      return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
    }

    exec(command, (error, stdout, stderr) => {
      if (error) {
        console.error(`exec error: ${error}`);
      }
    });

    return NextResponse.json({ success: true, message: `${action} executed.` });
  } catch (err: any) {
    console.error("Action error:", err);
    return NextResponse.json({ error: err.message || 'Failed to execute action' }, { status: 500 });
  }
}
