(function(){
var status='all',q=document.getElementById('q');
function apply(){
  var s=q.value.toLowerCase();
  document.querySelectorAll('.case').forEach(function(c){
    var okS=status==='all'||c.dataset.statuses.split(' ').indexOf(status)>-1;
    var okQ=!s||c.dataset.search.indexOf(s)>-1;
    c.style.display=(okS&&okQ)?'':'none';
  });
}
document.querySelectorAll('[data-st]').forEach(function(b){
  b.onclick=function(){status=b.dataset.st;
    document.querySelectorAll('[data-st]').forEach(function(x){x.classList.toggle('on',x===b)});apply();};
});
q.oninput=apply;
document.getElementById('exp').onclick=function(){document.querySelectorAll('details.sec').forEach(function(d){d.open=true})};
document.getElementById('col').onclick=function(){document.querySelectorAll('details.sec').forEach(function(d){d.open=false})};
})();
