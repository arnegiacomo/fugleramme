# Showcase

Frames people have running around the world. Click one to open it.

<style>
  .frames {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 1rem;
    margin: 1.5rem 0;
  }
  .frames figure {
    margin: 0;
  }
  .frames a {
    display: block;
    color: inherit;
  }
  .frames img {
    display: block;
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: contain;
    background: var(--md-code-bg-color);
    border-radius: 0.2rem;
  }
  .frames figcaption {
    margin-top: 0.4rem;
    font-size: 0.8rem;
    line-height: 1.4;
  }
  .frames small {
    display: block;
    opacity: 0.7;
  }
</style>

<div class="frames">
  <figure>
    <a href="https://fugleramme.arnegiacomo.dev">
      <img src="https://fugleramme.arnegiacomo.dev/collage.png" alt="The frame in Bergen, Norway" loading="lazy" referrerpolicy="no-referrer">
      <figcaption>Bergen, Norway <small>fugleramme.arnegiacomo.dev</small></figcaption>
    </a>
  </figure>
  <figure>
    <a href="https://birdies.semmel.org">
      <img src="https://birdies.semmel.org/collage.png" alt="The frame in Möhlin, Switzerland" loading="lazy" referrerpolicy="no-referrer">
      <figcaption>Möhlin, Switzerland <small>birdies.semmel.org</small></figcaption>
    </a>
  </figure>
  <figure>
    <a href="https://fugleramme.does-it.net/">
      <img src="https://fugleramme.does-it.net/collage.png" alt="The frame at Lake Wohlen, Switzerland" loading="lazy" referrerpolicy="no-referrer">
      <figcaption>Lake Wohlen, Switzerland <small>fugleramme.does-it.net</small></figcaption>
    </a>
  </figure>
  <figure>
    <a href="https://hagegjester.oyvij.dev/">
      <img src="https://hagegjester.oyvij.dev/collage.png" alt="The frame in Os, Norway" loading="lazy" referrerpolicy="no-referrer">
      <figcaption>Os, Norway <small>hagegjester.oyvij.dev</small></figcaption>
    </a>
  </figure>
  <figure>
    <a href="https://fugleramme.gabi.is/">
      <img src="https://fugleramme.gabi.is/collage.png" alt="The frame in Sevilla, Spain" loading="lazy" referrerpolicy="no-referrer">
      <figcaption>Sevilla, Spain <small>fugleramme.gabi.is</small></figcaption>
    </a>
  </figure>
</div>

Running one yourself and want to share with others? Post the link in
[Want to share your frame?](https://github.com/arnegiacomo/fugleramme/discussions/146) or open a PR adding it here.
Listing a frame means visitors to this page load its collage straight from your
Pi, so expect some image traffic.
