// trio_io.js — фасад над каноническим TRIOMAT1
const { writeTriomat1 } = require('./trio_to_octave');
const { readTriomat } = require('./readTriomat');
module.exports = { writeTriomat1, readTriomat };
