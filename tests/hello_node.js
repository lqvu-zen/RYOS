const os = require("os");

console.log("Hello from Node.js!");
console.log(`  Version : ${process.version}`);
console.log(`  Platform: ${os.platform()} ${os.release()}`);
console.log(`  Args    : ${process.argv.slice(2)}`);
