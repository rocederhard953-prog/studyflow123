/* Russian count forms: 1 задание, 2 задания, 5 заданий, 11 заданий, 21 задание. */
function ruPlural(value,one,few,many){const n=Math.abs(Number(value));if(!Number.isFinite(n))return many;if(!Number.isInteger(n))return few;const hundred=n%100,ten=n%10;return hundred>=11&&hundred<=14?many:ten===1?one:ten>=2&&ten<=4?few:many;}
function ruCount(value,one,few,many){return `${value} ${ruPlural(value,one,few,many)}`;}
if(typeof module==='object'&&module.exports)module.exports={ruPlural,ruCount};
