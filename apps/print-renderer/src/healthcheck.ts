/** Bounded local probe, including the private Unix-socket deployment. */
import {request} from 'node:http';
const path=process.env.CISSTAT_PRINT_RENDERER_SOCKET;
const req=request(path?{socketPath:path,path:'/readyz',method:'GET'}:{host:'127.0.0.1',port:Number(process.env.CISSTAT_PRINT_RENDERER_PORT||8907),path:'/readyz'},res=>{
  res.resume();res.once('end',()=>process.exit(res.statusCode===200?0:1));
});
const timer=setTimeout(()=>{req.destroy();process.exit(1);},12000);timer.unref();
req.on('error',()=>process.exit(1));req.end();
