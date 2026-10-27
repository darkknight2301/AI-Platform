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
  var root=document.documentElement,tb=document.getElementById('theme');
  function sysDark(){return window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches}
  function setTheme(t,save){
    root.setAttribute('data-theme',t);
    tb.textContent=t==='dark'?'\u2600 Light':'\u263E Dark';
    if(save){try{localStorage.setItem('report-theme',t)}catch(e){}}
  }
  var saved=null;try{saved=localStorage.getItem('report-theme')}catch(e){}
  setTheme(saved==='dark'||saved==='light'?saved:(sysDark()?'dark':'light'),false);
  tb.onclick=function(){setTheme(root.getAttribute('data-theme')==='dark'?'light':'dark',true)};
  document.getElementById('exp').onclick=function(){document.querySelectorAll('details.sec').forEach(function(d){d.open=true})};
  document.getElementById('col').onclick=function(){document.querySelectorAll('details.sec').forEach(function(d){d.open=false})};
  })();