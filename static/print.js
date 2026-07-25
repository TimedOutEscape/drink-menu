(function () {
  var MIN_SCALE = 0.55;
  var STEP = 0.05;

  function fitMenu() {
    var content = document.querySelector(".page-content");
    var sections = document.querySelector(".sections");
    if (!content || !sections) return;

    var scale = 1;
    content.style.setProperty("--menu-scale", scale);

    while (
      scale > MIN_SCALE &&
      sections.scrollWidth > sections.clientWidth + 1
    ) {
      scale = Math.max(MIN_SCALE, scale - STEP);
      content.style.setProperty("--menu-scale", scale);
    }
  }

  if (document.readyState === "complete") {
    fitMenu();
  } else {
    window.addEventListener("load", fitMenu);
  }
  window.addEventListener("beforeprint", fitMenu);
  window.addEventListener("resize", fitMenu);
})();
